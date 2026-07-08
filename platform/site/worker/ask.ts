// Server-side counterpart to scripts/rag_ask.py: retrieval here runs inside
// the Worker over a small pre-built keyword index (platform/scripts/
// build_site_data.py writes /data/ask_index.json — title/tags/preview words,
// deduped, per document), then the assembled context + question go to the
// same free OpenCode Zen model. The API key lives only as a Worker secret —
// never sent to the browser — so this is the only place it's safe to call it.
//
// Every call from here has come back `FreeUsageLimitError` regardless of API
// key or which free model, while the exact same key from a residential
// connection (scripts/rag_ask.py) works — i.e. OpenCode Zen is throttling
// Cloudflare Workers' shared egress IP range specifically, not the account.
// Sending explicit browser-like headers below in case that's read as a bot
// signal on their side; that alone didn't fix it, so the actual fix changes
// the network path: requests go to `scripts/llm_relay.py` — a tiny server on
// ANY residential machine (yours, a friend's, a Raspberry Pi — whoever is
// currently running `scripts/run_relay_stack.sh`), reached through a
// Cloudflare Tunnel — which then calls OpenCode Zen from that residential IP
// instead of Cloudflare's. The OpenCode API key lives only on that machine,
// never as a Cloudflare secret.
//
// Whoever runs the relay doesn't need Cloudflare account access: their
// script self-registers its current tunnel URL with this Worker by calling
// POST /api/relay/register (authenticated with RELAY_SHARED_SECRET, a lower-
// stakes secret than the OpenCode key — safe to hand to a friend), which
// stores it in the RELAY_STATE KV binding. Whoever registered most recently
// (within RELAY_STALE_MS) is used — so it works from any machine currently
// running the relay, without redeploying or touching `wrangler secret`.
// Falls back to the static `RELAY_URL` secret (legacy, single-machine setup)
// and then to the direct call (`OPENCODE_API_KEY`) if neither relay path is
// configured, for setups where the direct call isn't throttled.
//
// Deliberately NOT using a full-text search library (e.g. MiniSearch) here:
// tokenizing/indexing the whole corpus, or even just parsing+compiling that
// library's code, blew through the Workers free-plan CPU budget (~10ms) and
// every request failed with error 1102. A plain substring-overlap scan over
// a small pre-tokenized JSON file is cheap enough to fit comfortably.
//
// Comparison questions ("compare les types de documents (traité, accord,
// déclaration) et dis-moi s'il y a des différences de forme/rédaction") get a
// different, richer context: see `detectDocTypes`/`buildProfileBlock` and the
// comparison branch in `handleAsk` below, mirroring scripts/rag_ask.py's
// KnowledgeBase.detect_comparison_types / build_context. The extra data
// source is /data/doc_type_profiles.json
// (published by platform/scripts/build_site_data.py from
// outputs_v2/similarity/doc_type_profiles.json — see
// pdfkb/similarity/doc_type_profiles.py), a small static file with, per
// doc_type, the fraction of documents matching structural markers ("pleins
// pouvoirs" preamble, numbered articles, "En foi de quoi" signature clause,
// ...) plus a couple of real excerpts. Fetching it costs one more cached
// ASSETS.fetch, no extra CPU-heavy parsing, so it stays within the Workers
// free-plan budget same as the ask index.

// Minimal structural type for a Workers KV binding — avoids adding
// @cloudflare/workers-types as a devDependency just for this.
interface KVNamespaceLike {
  get(key: string): Promise<string | null>;
  put(key: string, value: string): Promise<void>;
}

export interface Env {
  ASSETS: Fetcher;
  OPENCODE_API_KEY?: string;
  // Dynamic, multi-machine path (see module header comment): whichever
  // relay last called POST /api/relay/register has its URL stored here.
  RELAY_STATE?: KVNamespaceLike;
  // Legacy/manual path: a fixed residential relay URL set once via
  // `wrangler secret put RELAY_URL`, e.g. "https://xxxx.trycloudflare.com/ask".
  // Only used if RELAY_STATE has no fresh registration.
  RELAY_URL?: string;
  RELAY_SHARED_SECRET?: string;
}

const API_URL = "https://opencode.ai/zen/v1/chat/completions";
const DEFAULT_MODEL = "big-pickle";
// Free (no-cost) OpenCode Zen models -- kept in sync by hand against
// `curl https://opencode.ai/zen/v1/models` (only "-free"-suffixed ids, plus
// "big-pickle" which OpenCode itself designates as its free flagship model,
// see scripts/rag_ask.py's header). Mirrored in AskAssistant.astro's
// dropdown and scripts/llm_relay.py's whitelist -- the client can only ever
// pick from this exact list (see resolveModel), so there's no way to smuggle
// a paid model id through the request body and run up someone's bill.
const FREE_MODELS: { id: string; label: string }[] = [
  { id: "big-pickle", label: "Big Pickle (par défaut)" },
  { id: "deepseek-v4-flash-free", label: "DeepSeek V4 Flash" },
  { id: "mimo-v2.5-free", label: "MiMo V2.5" },
  { id: "hy3-free", label: "Hunyuan 3" },
  { id: "nemotron-3-ultra-free", label: "Nemotron 3 Ultra" },
  { id: "north-mini-code-free", label: "North Mini Code" }
];
const FREE_MODEL_IDS = new Set(FREE_MODELS.map((m) => m.id));

function resolveModel(requested: unknown): string {
  return typeof requested === "string" && FREE_MODEL_IDS.has(requested) ? requested : DEFAULT_MODEL;
}
// Retrieval is two-stage, not a flat top-K keyword scan:
//   1. seed  -- a small keyword-overlap search (searchAskIndex), cheap and
//      precise for "does this document mention the query's words".
//   2. expand -- for each seed, pull in its already-precomputed similarity-
//      graph neighbours (DocDetail.similar_documents, built offline in
//      platform/scripts/build_site_data.py::build_similarity from FAISS/
//      LaBSE embeddings + lexical similarity -- see pdfkb/similarity). This
//      is genuine semantic relevance propagation (documents *about the same
//      thing* as a good keyword hit, even if they don't share its exact
//      words), reusing data that's already published rather than running any
//      embedding model inside the Worker (not feasible under Workers' CPU
//      budget -- see the module header on why full-text search libraries
//      were ruled out for the same reason).
// This mirrors scripts/rag_ask.py's local pipeline in spirit: that one does
// real FAISS nearest-neighbour search at query time (only possible locally,
// where sentence-transformers can run); here, the *graph edges FAISS already
// produced offline* stand in for a live vector search.
const SEED_HITS = 6;
// Of the full relevant set (below), only this many actually get fetched in
// full and go into the LLM's context/citations -- keeps prompt size and
// subrequest count sane. The rest are still returned to the client (as
// `browse`, title/year/type/score only, no extra fetches) so the person
// asking can scroll and open anything the retrieval considered relevant,
// not just the subset the model happened to quote from.
const FINAL_HITS = 10;
// Per-seed cap on how many graph neighbours feed the *browsable* set. 10 is
// the ceiling anyway -- platform/scripts/build_site_data.py only publishes
// each document's top 10 similarity-graph neighbours.
const GRAPH_BROWSE_PER_SEED = 10;
const BROWSE_LIMIT = 60;
// Comparison questions ("compare traité, accord, déclaration...") seed and
// expand *per named type* so an under-represented type isn't crowded out --
// same reasoning as scripts/rag_ask.py's search_by_doc_type.
const COMPARE_SEED_PER_TYPE = 3;
const COMPARE_FINAL_PER_TYPE = 5;
const COMPARE_BROWSE_LIMIT_PER_TYPE = 25;
const RELAY_STATE_KEY = "active_relay";
// A relay that hasn't re-registered in this long is assumed offline (its
// machine went to sleep, the tunnel died, ...) rather than trying a dead URL.
const RELAY_STALE_MS = 10 * 60 * 1000;

const SYSTEM_PROMPT =
  "Tu es un assistant de recherche qui répond STRICTEMENT à partir des extraits de documents " +
  "fournis (corpus de traités et instruments juridiques Lexis Mollis, OCR historique, parfois " +
  "imparfait). Si l'information n'est pas dans le contexte fourni, dis-le clairement plutôt que " +
  "d'inventer. Cite systématiquement l'identifiant de document entre crochets (ex. [16460004_s1]) " +
  "et l'année quand c'est pertinent. Réponds dans la langue de la question. Si le contexte contient " +
  "des sections « Profil du type documentaire », base toute comparaison de forme/rédaction entre " +
  "types de documents sur les statistiques qu'elles donnent (fractions de documents, moyennes) — " +
  "ces statistiques portent sur l'ENSEMBLE des documents de ce type dans le corpus, pas seulement " +
  "sur les extraits cités ci-dessous. Précise systématiquement le nombre total de documents sur " +
  "lequel chaque statistique est calculée (donné en début de chaque profil, ex. « 387 document(s) " +
  "classé(s) « Accord » ») pour que la fiabilité statistique soit explicite, cite les pourcentages " +
  "exacts plutôt que des impressions générales, et illustre chaque affirmation avec au moins un " +
  "extrait réel cité [identifiant] tiré des exemples fournis. Si le contexte contient une section " +
  "« Note méthodologique », respecte-la STRICTEMENT : pour la partie qu'elle concerne, ne donne " +
  "AUCUN pourcentage ni statistique de corpus, indique explicitement qu'il s'agit d'une recherche " +
  "libre sur un terme non reconnu comme catégorie officielle, et limite-toi à décrire prudemment ce " +
  "qui est observable dans les extraits cités pour cette partie.";

// Mirrors the keys of metadata_design/doc_type_mapping.json (kept in sync by hand —
// it changes rarely; see PROJECT_STATUS.md if it drifts).
const DOC_TYPE_LABELS = [
  "Accord", "Accusé de réception", "Arrangement", "Autre", "Certificat", "Convention", "Déclaration",
  "Échange de lettres", "Échange de notes", "Inconnu", "Instrument d'acceptation", "Instrument d'adhésion",
  "Instrument d'approbation", "Instrument de ratification", "Instrument de succession",
  "Lettre", "Memorandum", "Minutes", "Note verbale", "Notification", "Pouvoirs", "Procès-verbal",
  "Protocole", "Texte", "Traité"
];

interface AskIndexDoc {
  id: string;
  title?: string;
  year?: number;
  doc_type?: string;
  treaty_id?: string;
  kw?: string;
}

interface SearchHit extends AskIndexDoc {
  document_id: string;
  score: number;
  // Set when this hit was pulled in via graph expansion (similar_documents)
  // rather than directly matching the query's keywords -- surfaced in
  // buildContext so both the LLM and the `sources` list are transparent
  // about why a given document is in context.
  viaGraph?: boolean;
  // Set on entries in the broader `browse` list (see handleAsk) that also
  // made it into the LLM's actual context/citations, vs. ones that were
  // identified as relevant but not sent to the model (still worth surfacing
  // for a person to scroll through and open directly).
  usedInAnswer?: boolean;
}

interface DocDetail {
  document_id: string;
  title?: string;
  year?: number;
  doc_type?: string;
  treaty_id?: string;
  text_preview?: string;
  similar_documents?: { document_id: string; title?: string; type?: string; score?: number }[];
}

interface DocTypeProfile {
  label?: string;
  instrument_type?: string;
  legal_force?: string;
  narrative_fr?: string;
  n_documents?: number;
  low_sample_warning?: boolean;
  sample_openings?: { document_id?: string; year?: number; excerpt?: string }[];
}

interface DocTypeProfiles {
  types?: Record<string, DocTypeProfile>;
}

let cachedAskIndex: AskIndexDoc[] | null = null;

async function loadAskIndex(env: Env, origin: string): Promise<AskIndexDoc[]> {
  if (cachedAskIndex) return cachedAskIndex;
  const response = await env.ASSETS.fetch(new URL("/data/ask_index.json", origin));
  cachedAskIndex = ((await response.json()) as AskIndexDoc[]) || [];
  return cachedAskIndex;
}

let cachedDocTypeProfiles: DocTypeProfiles | null = null;

async function loadDocTypeProfiles(env: Env, origin: string): Promise<DocTypeProfiles> {
  if (cachedDocTypeProfiles) return cachedDocTypeProfiles;
  const response = await env.ASSETS.fetch(new URL("/data/doc_type_profiles.json", origin));
  cachedDocTypeProfiles = response.ok ? ((await response.json()) as DocTypeProfiles) : { types: {} };
  return cachedDocTypeProfiles;
}

// French-normalisation for doc_type mention detection: lowercase, accents stripped,
// non-alphanumerics collapsed to single spaces — same idea as
// pdfkb/similarity/lexical.py's normalise_lexical, kept independent here since this
// runs in a Worker (no shared runtime with the Python pipeline).
function normaliseFr(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "") // strip combining diacritics after NFD decomposition
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function labelVariants(label: string): string[] {
  const norm = normaliseFr(label);
  if (!norm) return [];
  const variants = new Set([norm]);
  const words = norm.split(" ");
  if (!norm.endsWith("s")) variants.add(`${norm}s`);
  const lastWord = words[words.length - 1];
  if (words.length > 1 && !lastWord.endsWith("s")) {
    variants.add([...words.slice(0, -1), `${lastWord}s`].join(" "));
  }
  return Array.from(variants);
}

function detectDocTypes(query: string, labels: string[]): string[] {
  const padded = ` ${normaliseFr(query)} `;
  return labels.filter((label) => labelVariants(label).some((variant) => padded.includes(` ${variant} `)));
}

// Heuristic: does this question sound like it's trying to compare document
// types at all? Deliberately loose (substring match on the normalised
// query) -- false positives just mean an unnecessary but harmless
// clarification; false negatives are the real risk (a comparison-shaped
// question silently falling back to plain retrieval with no explanation,
// which is exactly what happened when someone asked to compare "Traité" and
// "Memorandum" -- the latter isn't one of the corpus's controlled labels).
function hasComparisonIntent(query: string): boolean {
  const normalised = normaliseFr(query);
  return ["compar", "differenc", "distinction"].some((needle) => normalised.includes(needle));
}

// When a question clearly wants a type-vs-type comparison but fewer than 2
// of the named terms match the corpus's actual controlled doc_type
// vocabulary, answer deterministically instead of leaving it to the LLM to
// notice and explain (which it *can* do correctly, as observed, but
// inconsistently and without ever telling the person what the real options
// are). Returns null when this doesn't apply (either it's not a comparison
// question, or it already has >=2 valid types and can proceed normally).
function buildUnmatchedTypeClarification(
  query: string,
  compareTypes: string[],
  docTypeProfiles: DocTypeProfiles
): string | null {
  if (compareTypes.length >= 2 || !hasComparisonIntent(query)) return null;

  const available = Object.values(docTypeProfiles.types || {})
    .filter((profile): profile is DocTypeProfile & { label: string } => Boolean(profile.label && profile.n_documents))
    .sort((a, b) => (b.n_documents ?? 0) - (a.n_documents ?? 0))
    .map((profile) => `${profile.label} (${profile.n_documents})`)
    .join(", ");

  const matchedNote = compareTypes.length
    ? `Type reconnu dans votre question : « ${compareTypes[0]} ». Le ou les autres termes utilisés ne correspondent à aucun type du corpus. `
    : "Aucun des termes utilisés ne correspond à un type reconnu du corpus. ";

  return (
    "Votre question semble demander une comparaison entre types de documents, mais elle ne peut pas être traitée " +
    "telle quelle : " +
    matchedNote +
    "Cette classification (indépendante de cette question) ne connaît que les types suivants, avec leur nombre de " +
    `documents dans le corpus : ${available}. ` +
    "Reformulez votre question en citant deux de ces types exacts, par exemple : « Compare les types Traité et " +
    "Accord et dis-moi s'il y a des différences de forme/rédaction »."
  );
}

// Companion to buildUnmatchedTypeClarification, for the case where we DON'T
// want to refuse outright: compareTypes has 0 or 1 real matches but there's
// still a genuine comparison intent. Rather than hard-stopping, handleAsk
// now falls through to a "degraded compare" retrieval (free-text search
// standing in for the unmatched term(s), no corpus-wide stats attached) and
// uses this text both as a context block telling the LLM exactly how to
// caveat that part of the answer, and as a `degraded_notice` field the UI
// can render as a visible disclaimer alongside a real answer.
function buildDegradedNotice(compareTypes: string[], docTypeProfiles: DocTypeProfiles): string {
  const available = Object.values(docTypeProfiles.types || {})
    .filter((profile): profile is DocTypeProfile & { label: string } => Boolean(profile.label && profile.n_documents))
    .sort((a, b) => (b.n_documents ?? 0) - (a.n_documents ?? 0))
    .map((profile) => `${profile.label} (${profile.n_documents})`)
    .join(", ");
  const subject = compareTypes.length
    ? `« ${compareTypes[0]} » est un type reconnu du corpus (statistiques ci-dessous). L'autre terme utilisé dans ` +
      "votre question"
    : "Aucun des termes utilisés dans votre question";
  return (
    `### Note méthodologique (à respecter strictement dans ta réponse)\n\n${subject} ne correspond à aucun des ` +
    "types officiels du corpus. Les extraits montrés pour ce terme proviennent d'une recherche libre sur le " +
    "texte/titre des documents, pas d'une catégorie auditée : aucune statistique de pourcentage n'existe pour " +
    `cette partie de la comparaison, seulement les exemples concrets cités. Types officiels disponibles avec leur ` +
    `nombre de documents dans le corpus : ${available}.`
  );
}

function searchAskIndex(query: string, docs: AskIndexDoc[], limit: number): SearchHit[] {
  const queryWords = Array.from(new Set(query.toLowerCase().match(/[a-zà-öø-ÿ0-9]{3,}/g) || []));
  if (!queryWords.length) return [];
  const scored: SearchHit[] = [];
  for (const doc of docs) {
    const kw = doc.kw || "";
    let score = 0;
    for (const word of queryWords) {
      if (kw.includes(word)) score += 1;
    }
    if (score > 0) scored.push({ ...doc, document_id: doc.id, score });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, limit);
}

async function fetchDocDetail(env: Env, origin: string, documentId: string): Promise<DocDetail | null> {
  const response = await env.ASSETS.fetch(new URL(`/data/docs/${encodeURIComponent(documentId)}.json`, origin));
  if (!response.ok) return null;
  return (await response.json()) as DocDetail;
}

function buildContext(hits: SearchHit[], details: (DocDetail | null)[]): string {
  const blocks: string[] = [];
  hits.forEach((hit, i) => {
    const detail = details[i];
    const title = detail?.title || hit.title || hit.document_id;
    const provenance = hit.viaGraph
      ? "trouvé via graphe de similarité"
      : "correspondance mots-clés";
    const lines = [
      `### [${hit.document_id}] ${title} (${detail?.year ?? hit.year ?? "année n/a"}, score=${hit.score.toFixed(2)}, ${provenance})`,
      `Traité : ${detail?.treaty_id || hit.treaty_id || "n/a"} · Type : ${detail?.doc_type || hit.doc_type || "n/a"}`,
      "",
      (detail?.text_preview || "").trim()
    ];
    const related = (detail?.similar_documents || []).slice(0, 4);
    if (related.length) {
      lines.push(
        "",
        "Documents liés : " +
          related
            .map((r) => `${r.title || r.document_id} [${r.document_id}] (${r.type || "similar_to"}, ${Number(r.score ?? 0).toFixed(2)})`)
            .join("; ")
      );
    }
    blocks.push(lines.join("\n"));
  });
  return blocks.join("\n\n---\n\n");
}

function buildProfileBlock(label: string, profile: DocTypeProfile): string {
  const lines = [
    `### Profil du type documentaire « ${label} » (${profile.instrument_type || "n/a"}, force juridique=${profile.legal_force || "n/a"})`,
    profile.narrative_fr || ""
  ];
  const openings = (profile.sample_openings || []).slice(0, 2);
  if (openings.length) {
    lines.push("", "Exemples réels (débuts de document) :");
    for (const sample of openings) {
      lines.push(`- [${sample.document_id}] (${sample.year ?? "n/a"}) : « ${sample.excerpt} »`);
    }
  }
  return lines.join("\n");
}

async function askLLMDirect(question: string, context: string, apiKey: string, model: string): Promise<string> {
  const response = await fetch(API_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      Accept: "application/json",
      "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
      "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"
    },
    body: JSON.stringify({
      model,
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: `Contexte :\n\n${context}\n\n---\n\nQuestion : ${question}` }
      ],
      temperature: 0.2
    })
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`LLM ${response.status}: ${body.slice(0, 300)}`);
  }
  const data = (await response.json()) as { choices?: { message?: { content?: string } }[] };
  return data.choices?.[0]?.message?.content ?? "";
}

// Reads whichever relay most recently self-registered via /api/relay/register
// (see handleRelayRegister), ignoring stale entries — an offline relay that
// registered an hour ago shouldn't be tried forever.
async function getActiveRelayUrl(env: Env): Promise<string | null> {
  if (!env.RELAY_STATE) return null;
  const raw = await env.RELAY_STATE.get(RELAY_STATE_KEY);
  if (!raw) return null;
  try {
    const state = JSON.parse(raw) as { url?: string; updatedAt?: number };
    if (!state.url || typeof state.updatedAt !== "number") return null;
    if (Date.now() - state.updatedAt > RELAY_STALE_MS) return null;
    return state.url;
  } catch {
    return null;
  }
}

async function handleRelayRegister(request: Request, env: Env): Promise<Response> {
  if (!env.RELAY_STATE) {
    return Response.json({ error: "RELAY_STATE (KV binding) n'est pas configuré côté serveur." }, { status: 500 });
  }
  if (!env.RELAY_SHARED_SECRET || request.headers.get("X-Relay-Secret") !== env.RELAY_SHARED_SECRET) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  let url = "";
  try {
    const body = (await request.json()) as { url?: string };
    url = (body.url || "").trim();
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 });
  }
  if (!/^https:\/\/.+/.test(url)) {
    return Response.json({ error: "missing or invalid 'url'" }, { status: 400 });
  }
  await env.RELAY_STATE.put(RELAY_STATE_KEY, JSON.stringify({ url, updatedAt: Date.now() }));
  return Response.json({ ok: true, url });
}

// Diagnostic-only: reports exactly what the read path (getActiveRelayUrl)
// sees, including the raw KV value and computed staleness, so registration
// (write-side) and lookup (read-side) issues can be told apart instead of
// guessed at. Not authenticated -- it doesn't reveal anything beyond the
// relay's own tunnel URL, which is not itself a secret.
async function handleRelayStatus(env: Env): Promise<Response> {
  // Booleans only (never the secret values themselves) -- this is what
  // actually gates the relay branch in handleAsk: `relayUrl &&
  // env.RELAY_SHARED_SECRET`. If RELAY_SHARED_SECRET is false here despite
  // registration succeeding, that's the whole bug: the write path only needs
  // the secret to *authenticate the register call*, but the read path
  // (handleAsk) separately needs the SAME secret bound as a Worker secret on
  // *this* deployment to actually use the relay -- two different deploy
  // targets (root wrangler.jsonc vs platform/site/wrangler.jsonc) or two
  // different Cloudflare accounts can easily end up with the secret set on
  // one and not the other.
  const secretsPresent = {
    RELAY_SHARED_SECRET: Boolean(env.RELAY_SHARED_SECRET),
    OPENCODE_API_KEY: Boolean(env.OPENCODE_API_KEY)
  };
  if (!env.RELAY_STATE) {
    return Response.json({ configured: false, reason: "RELAY_STATE binding missing", secretsPresent });
  }
  const raw = await env.RELAY_STATE.get(RELAY_STATE_KEY);
  if (!raw) {
    return Response.json({ configured: true, registered: false, raw: null, secretsPresent });
  }
  let parsed: { url?: string; updatedAt?: number } | null = null;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return Response.json({ configured: true, registered: false, raw, parseError: true, secretsPresent });
  }
  const ageMs = parsed?.updatedAt ? Date.now() - parsed.updatedAt : null;
  const activeUrlWouldBe = await getActiveRelayUrl(env);
  return Response.json({
    configured: true,
    registered: true,
    raw,
    url: parsed?.url ?? null,
    updatedAt: parsed?.updatedAt ?? null,
    ageSeconds: ageMs !== null ? Math.round(ageMs / 1000) : null,
    staleMsThreshold: RELAY_STALE_MS,
    stale: ageMs !== null ? ageMs > RELAY_STALE_MS : null,
    activeUrlWouldBe,
    secretsPresent,
    // This mirrors handleAsk's exact gating condition -- if this is false
    // despite activeUrlWouldBe being set, RELAY_SHARED_SECRET is the bug.
    wouldUseRelay: Boolean(activeUrlWouldBe && env.RELAY_SHARED_SECRET)
  });
}

// Preferred path — see module header comment. `relayUrl` is the full /ask URL
// of scripts/llm_relay.py, exposed through a Cloudflare Tunnel. The relay adds
// the SYSTEM_PROMPT and calls OpenCode Zen itself (from a residential IP), so
// only the raw question + context need to travel over the tunnel.
async function askLLMViaRelay(
  question: string,
  context: string,
  relayUrl: string,
  sharedSecret: string,
  model: string
): Promise<string> {
  const response = await fetch(relayUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Relay-Secret": sharedSecret },
    body: JSON.stringify({ question, context, model })
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Relay ${response.status}: ${body.slice(0, 300)}`);
  }
  const data = (await response.json()) as { answer?: string; error?: string };
  if (data.error) throw new Error(data.error);
  return data.answer ?? "";
}

// Pulls in graph neighbours of `seedHits` (via each seed's already-fetched
// DocDetail.similar_documents) up to `limit`, skipping anything in
// `exclude`. `typeFilter`, when given, only keeps a candidate whose doc_type
// (looked up in `docsById`, since similar_documents' own "type" field is the
// *edge* type like "similar_to", not the target document's doc_type) matches
// -- used by comparison mode to keep expansion within the named type instead
// of drifting into whichever type happens to dominate the similarity graph.
function expandViaGraph(
  seedHits: SearchHit[],
  seedDetails: (DocDetail | null)[],
  docsById: Map<string, AskIndexDoc>,
  exclude: Set<string>,
  limit: number,
  perSeedCap: number,
  typeFilter?: string
): SearchHit[] {
  const candidates: SearchHit[] = [];
  const localSeen = new Set<string>();
  seedHits.forEach((seed, i) => {
    // Cap how many neighbours a single seed can contribute, so one
    // well-connected document doesn't crowd out the others' neighbourhoods.
    const related = (seedDetails[i]?.similar_documents || []).slice(0, perSeedCap);
    for (const rel of related) {
      if (!rel.document_id || exclude.has(rel.document_id) || localSeen.has(rel.document_id)) continue;
      if (typeFilter && docsById.get(rel.document_id)?.doc_type !== typeFilter) continue;
      localSeen.add(rel.document_id);
      candidates.push({
        id: rel.document_id,
        document_id: rel.document_id,
        title: rel.title,
        doc_type: docsById.get(rel.document_id)?.doc_type,
        score: Number(rel.score ?? 0),
        viaGraph: true
      });
    }
  });
  candidates.sort((a, b) => b.score - a.score);
  return candidates.slice(0, Math.max(0, limit));
}

interface RetrievalResult {
  hits: SearchHit[];
  details: (DocDetail | null)[];
  browse: SearchHit[];
}

// The one retrieval primitive behind every branch of handleAsk: seed with
// keyword search over `candidateDocs`, then expand via the similarity graph
// (optionally restricted to `typeFilter`), tracking `exclude` so repeated
// calls (e.g. once per named type, then once more for a free-text fallback)
// never return the same document twice. Used identically whether
// `candidateDocs` is the whole corpus (plain questions, free-text fallback)
// or pre-filtered to one doc_type (descriptive or comparison questions) --
// there is deliberately no separate code path per scenario, only different
// arguments, so fixing or tuning retrieval happens in exactly one place.
async function retrieveSeedsAndExpand(
  query: string,
  candidateDocs: AskIndexDoc[],
  env: Env,
  origin: string,
  docsById: Map<string, AskIndexDoc>,
  exclude: Set<string>,
  seedCap: number,
  finalCap: number,
  browseCap: number,
  graphPerSeedCap: number,
  typeFilter?: string
): Promise<RetrievalResult> {
  let seeds = searchAskIndex(query, candidateDocs, seedCap).filter((hit) => !exclude.has(hit.document_id));
  // A descriptive question ("caractéristiques d'un memorandum") often shares
  // no keywords at all with the documents themselves -- fall back to just
  // taking a few documents of the candidate set directly rather than ending
  // up with zero excerpts (the profile block's own sample_openings help too,
  // but real citable excerpts are better where available).
  if (!seeds.length && candidateDocs.length) {
    seeds = candidateDocs
      .filter((doc) => !exclude.has(doc.id))
      .slice(0, seedCap)
      .map((doc) => ({ ...doc, document_id: doc.id, score: 0 }));
  }
  seeds.forEach((hit) => exclude.add(hit.document_id));
  const seedDetails = await Promise.all(seeds.map((hit) => fetchDocDetail(env, origin, hit.document_id)));

  const browseExpanded = expandViaGraph(seeds, seedDetails, docsById, exclude, browseCap, graphPerSeedCap, typeFilter);
  const expanded = browseExpanded.slice(0, Math.max(0, finalCap - seeds.length));
  expanded.forEach((hit) => exclude.add(hit.document_id));
  const expandedDetails = await Promise.all(expanded.map((hit) => fetchDocDetail(env, origin, hit.document_id)));

  const hits = [...seeds, ...expanded];
  const details = [...seedDetails, ...expandedDetails];
  const usedIds = new Set(hits.map((hit) => hit.document_id));
  const browse = [
    ...seeds.map((hit) => ({ ...hit, usedInAnswer: true })),
    ...browseExpanded.map((hit) => ({ ...hit, usedInAnswer: usedIds.has(hit.document_id) }))
  ];
  return { hits, details, browse };
}

async function handleAsk(request: Request, env: Env, origin: string): Promise<Response> {
  let query = "";
  let model = DEFAULT_MODEL;
  try {
    const body = (await request.json()) as { query?: string; model?: string };
    query = (body.query || "").trim();
    model = resolveModel(body.model);
  } catch {
    return Response.json({ error: "Corps de requête JSON invalide." }, { status: 400 });
  }
  if (!query) {
    return Response.json({ error: "Question vide." }, { status: 400 });
  }

  const askDocs = await loadAskIndex(env, origin);
  const docsById = new Map(askDocs.map((doc) => [doc.id, doc]));
  const docTypeProfiles = await loadDocTypeProfiles(env, origin);
  const compareTypes = detectDocTypes(query, DOC_TYPE_LABELS).filter((label) => docTypeProfiles.types?.[label]);
  // A comparison-shaped question ("compare X et Y") with fewer than 2 real
  // corpus doc_types matched used to hard-refuse via
  // buildUnmatchedTypeClarification. It now falls through to a "degraded
  // compare" instead: whichever term(s) DID match still get a real,
  // rigorous profile; the unmatched term is covered by plain free-text
  // search, clearly disclaimed (see buildDegradedNotice) rather than
  // silently treated as an official category, or silently refused outright.
  const degradedCompare = compareTypes.length < 2 && hasComparisonIntent(query);
  // Set only inside the degradedCompare branch below; surfaced to the client
  // as `degraded_notice` so the UI can render it as a visible disclaimer
  // alongside a real (partial) answer.
  let degradedNotice: string | undefined;

  let hits: SearchHit[];
  let details: (DocDetail | null)[];
  let contextBlocks: string[];
  // Broader than `hits`: every document the retrieval considered relevant
  // (seeds + all their graph neighbours, up to BROWSE_LIMIT /
  // COMPARE_BROWSE_LIMIT_PER_TYPE), not just the smaller subset that fit
  // into the LLM's context. Returned to the client so a person can scroll
  // and open any of them directly, not only the ones the model quoted from.
  let browse: SearchHit[];

  if (compareTypes.length >= 1 || degradedCompare) {
    // Type-aware retrieval: the SAME mechanism whether exactly one real
    // corpus type is named (a descriptive question like "quelles sont les
    // caractéristiques d'un memorandum ?") or several (an explicit
    // comparison) -- both get a real corpus-wide profile per named type plus
    // retrieval restricted to that type, via one shared loop over
    // retrieveSeedsAndExpand, instead of near-duplicate code per scenario.
    // This is what fixed the "memorandum" bug: previously only >=2 named
    // types got type-restricted retrieval at all, so a single-type question
    // fell through to whole-corpus keyword search, which could surface
    // documents having nothing to do with the named type.
    const multiType = compareTypes.length > 1;
    const seedCap = multiType ? COMPARE_SEED_PER_TYPE : SEED_HITS;
    const finalCap = multiType ? COMPARE_FINAL_PER_TYPE : FINAL_HITS;
    const browseCap = multiType ? COMPARE_BROWSE_LIMIT_PER_TYPE : BROWSE_LIMIT;

    const profileBlocks = compareTypes.map((label) => buildProfileBlock(label, docTypeProfiles.types![label]));
    const seen = new Set<string>();
    hits = [];
    details = [];
    browse = [];
    for (const label of compareTypes) {
      const typedDocs = askDocs.filter((doc) => doc.doc_type === label);
      const result = await retrieveSeedsAndExpand(
        query,
        typedDocs,
        env,
        origin,
        docsById,
        seen,
        seedCap,
        finalCap,
        browseCap,
        GRAPH_BROWSE_PER_SEED,
        label
      );
      hits.push(...result.hits);
      details.push(...result.details);
      browse.push(...result.browse);
    }
    contextBlocks = [...profileBlocks];

    // A comparison-shaped question ("compare X et Y") where fewer than 2 of
    // the named terms matched a real type used to hard-refuse via
    // buildUnmatchedTypeClarification. It now falls through to this same
    // type-aware path for whichever term(s) DID match, PLUS an honest,
    // unrestricted free-text search standing in for the unmatched term(s) --
    // see buildDegradedNotice for exactly how that's disclaimed rather than
    // silently treated as an official category, or silently refused outright.
    if (degradedCompare) {
      const freeResult = await retrieveSeedsAndExpand(
        query,
        askDocs,
        env,
        origin,
        docsById,
        seen,
        SEED_HITS,
        FINAL_HITS,
        BROWSE_LIMIT,
        GRAPH_BROWSE_PER_SEED
      );
      hits.push(...freeResult.hits);
      details.push(...freeResult.details);
      browse.push(...freeResult.browse);

      if (!hits.length) {
        // Genuinely nothing to answer from even with an unrestricted
        // free-text fallback -- fall back to the deterministic clarification
        // rather than sending an empty context to the LLM.
        return Response.json({
          answer:
            buildUnmatchedTypeClarification(query, compareTypes, docTypeProfiles) ||
            "Aucun document du corpus ne semble correspondre à cette question. Essayez une autre formulation.",
          sources: [],
          browse: [],
          profiles: undefined
        });
      }

      degradedNotice = buildDegradedNotice(compareTypes, docTypeProfiles);
      contextBlocks.unshift(degradedNotice);
    }

    if (hits.length) contextBlocks.push(buildContext(hits, details));
  } else {
    // Plain question: no known corpus type named at all -- seed with keyword
    // search over the whole corpus, then expand via the similarity graph.
    const result = await retrieveSeedsAndExpand(
      query,
      askDocs,
      env,
      origin,
      docsById,
      new Set<string>(),
      SEED_HITS,
      FINAL_HITS,
      BROWSE_LIMIT,
      GRAPH_BROWSE_PER_SEED
    );
    if (!result.hits.length) {
      return Response.json({
        answer: "Aucun document du corpus ne semble correspondre à cette question. Essayez une autre formulation.",
        sources: [],
        browse: []
      });
    }
    hits = result.hits;
    details = result.details;
    browse = result.browse;
    contextBlocks = [buildContext(hits, details)];
  }

  const context = contextBlocks.join("\n\n---\n\n");
  const sources = hits.map((hit) => ({
    document_id: hit.document_id,
    title: hit.title,
    year: hit.year,
    score: hit.score,
    via_graph: Boolean(hit.viaGraph)
  }));
  // Deduplicated, score-sorted version of the broader relevant set (see
  // `browse` above) for the client to render as a scrollable, clickable list
  // -- every document retrieval considered relevant, not just the ones that
  // fit into the LLM's context.
  const browseSeen = new Set<string>();
  const browseSources = browse
    .filter((hit) => {
      if (browseSeen.has(hit.document_id)) return false;
      browseSeen.add(hit.document_id);
      return true;
    })
    .sort((a, b) => b.score - a.score)
    .map((hit) => ({
      document_id: hit.document_id,
      title: hit.title,
      year: hit.year,
      doc_type: hit.doc_type,
      score: hit.score,
      via_graph: Boolean(hit.viaGraph),
      used_in_answer: Boolean(hit.usedInAnswer)
    }));
  // Separate from `sources` (the illustrative excerpts): the corpus-wide
  // statistical basis for a comparison answer, so callers (the /assistant/
  // UI, or anything else consuming this API) can show explicitly that "79.3%
  // numbered articles" etc. is measured over the type's full document count,
  // not just the handful of excerpts quoted above.
  const profiles =
    compareTypes.length >= 1
      ? compareTypes.map((label) => {
          const profile = docTypeProfiles.types![label];
          return {
            label,
            instrument_type: profile.instrument_type ?? null,
            n_documents: profile.n_documents ?? null,
            low_sample_warning: Boolean(profile.low_sample_warning)
          };
        })
      : undefined;

  const relayUrl = (await getActiveRelayUrl(env)) || env.RELAY_URL;
  if (relayUrl && env.RELAY_SHARED_SECRET) {
    try {
      const answer = await askLLMViaRelay(query, context, relayUrl, env.RELAY_SHARED_SECRET, model);
      return Response.json({ answer, sources, browse: browseSources, profiles, degraded_notice: degradedNotice, model });
    } catch (error) {
      return Response.json(
        {
          answer: null,
          sources,
          browse: browseSources,
          profiles,
          degraded_notice: degradedNotice,
          error: error instanceof Error ? error.message : String(error)
        },
        { status: 502 }
      );
    }
  }

  if (!env.OPENCODE_API_KEY) {
    return Response.json({
      answer: null,
      sources,
      browse: browseSources,
      profiles,
      degraded_notice: degradedNotice,
      error:
        "Aucun relais actif (voir scripts/run_relay_stack.sh) et OPENCODE_API_KEY n'est pas non " +
        "plus configuré côté serveur (wrangler secret put ...)."
    });
  }

  try {
    const answer = await askLLMDirect(query, context, env.OPENCODE_API_KEY, model);
    return Response.json({ answer, sources, browse: browseSources, profiles, degraded_notice: degradedNotice, model });
  } catch (error) {
    return Response.json(
      {
        answer: null,
        sources,
        browse: browseSources,
        profiles,
        degraded_notice: degradedNotice,
        error: error instanceof Error ? error.message : String(error)
      },
      { status: 502 }
    );
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/ask") {
      if (request.method !== "POST") {
        return new Response("Method Not Allowed", { status: 405 });
      }
      return handleAsk(request, env, url.origin);
    }
    if (url.pathname === "/api/relay/register") {
      if (request.method !== "POST") {
        return new Response("Method Not Allowed", { status: 405 });
      }
      return handleRelayRegister(request, env);
    }
    if (url.pathname === "/api/relay/status") {
      return handleRelayStatus(env);
    }
    if (url.pathname === "/api/models") {
      return Response.json({ models: FREE_MODELS, default: DEFAULT_MODEL });
    }
    return env.ASSETS.fetch(request);
  }
};
