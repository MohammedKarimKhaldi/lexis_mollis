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

// Minimal structural type for the Workers ExecutionContext -- same reasoning
// as KVNamespaceLike above. Needed so /api/ask's streamed response (see
// handleAsk) can keep running the retrieval+LLM work via ctx.waitUntil after
// the Response (backed by the stream's readable half) has already been
// returned to the caller.
interface ExecutionContextLike {
  waitUntil(promise: Promise<unknown>): void;
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
const RELAY_STATE_KEY = "active_relay";
// A relay that hasn't re-registered in this long is assumed offline (its
// machine went to sleep, the tunnel died, ...) rather than trying a dead URL.
const RELAY_STALE_MS = 10 * 60 * 1000;

const SYSTEM_PROMPT =
  "Tu es un assistant de recherche qui répond STRICTEMENT à partir des extraits de documents " +
  "fournis (corpus de traités et instruments juridiques Lexis Mollis, OCR historique, parfois " +
  "imparfait). Si l'information n'est pas dans le contexte fourni, dis-le clairement plutôt que " +
  "d'inventer. Cite systématiquement l'identifiant de document entre crochets (ex. [16460004_s1]) " +
  "et l'année quand c'est pertinent. Réponds en français par défaut, et toujours en français lorsque " +
  "la question est en français ; change de langue uniquement si la personne le demande explicitement. " +
  "Donne une réponse directe et concise ; ne mentionne jamais les lots, étapes, prompts ou mécanismes internes. " +
  "Si le contexte contient " +
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

interface DocumentsIndexEntry {
  document_id: string;
  title?: string;
  year?: number;
  doc_type?: string;
  text_preview?: string;
}

let cachedDocumentsIndex: DocumentsIndexEntry[] | null = null;

// Bulk per-document data (title/year/doc_type/text_preview for the WHOLE
// corpus in one file) -- fetched and cached once per Worker instance, same
// pattern as loadAskIndex. Used by the named-type retrieval path below
// instead of one fetchDocDetail() subrequest per document: a type like
// "Autre" (749 documents) or "Accord" (408) would otherwise need that many
// subrequests in a single request, comfortably over Cloudflare Workers'
// actual platform limit (50 on Free/Bundled plans) -- a real error, not a
// design preference, and not fixed by making the fetches sequential instead
// of parallel (the limit is on total count, not concurrency). Reading from
// this single bulk file avoids the problem entirely regardless of how many
// documents a type has. The one thing it doesn't carry is similar_documents
// (graph neighbours), only present in the per-document detail files -- an
// acceptable trade-off here since every document of the named type is
// already included directly.
async function loadDocumentsIndex(env: Env, origin: string): Promise<DocumentsIndexEntry[]> {
  if (cachedDocumentsIndex) return cachedDocumentsIndex;
  const response = await env.ASSETS.fetch(new URL("/data/documents.json", origin));
  cachedDocumentsIndex = response.ok ? ((await response.json()) as DocumentsIndexEntry[]) : [];
  return cachedDocumentsIndex;
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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const CALL_MODEL_MAX_RETRIES = 2;
const CALL_MODEL_RETRY_DELAY_MS = 600;

// Single entry point for "call the model, however that's currently wired up"
// -- relay (preferred, see module header) falling back to the direct call,
// throwing if neither is configured. Used by generateAnswer both for the
// plain single-call path and, repeatedly, inside the map-reduce path below,
// so the relay/direct/error-message logic exists in exactly one place.
//
// Retries transient failures (network blip, a momentary 5xx from OpenCode
// Zen, ...) a couple of times with backoff before giving up -- map-reduce
// over a large type makes many sequential calls (e.g. 14 for "Autre"), so
// without this, one flaky call out of many would throw away all the
// batches that already succeeded (see generateAnswer's partial-answer
// fallback for what happens if it still fails after retrying). Does NOT
// retry the "not configured at all" error -- that's not transient, retrying
// just delays showing the real fix to the person.
async function callModel(env: Env, question: string, context: string, model: string): Promise<string> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= CALL_MODEL_MAX_RETRIES; attempt++) {
    try {
      const relayUrl = (await getActiveRelayUrl(env)) || env.RELAY_URL;
      if (relayUrl && env.RELAY_SHARED_SECRET) {
        return await askLLMViaRelay(question, context, relayUrl, env.RELAY_SHARED_SECRET, model);
      }
      if (!env.OPENCODE_API_KEY) {
        throw new Error(
          "Aucun relais actif (voir scripts/run_relay_stack.sh) et OPENCODE_API_KEY n'est pas non plus configuré côté serveur (wrangler secret put ...)."
        );
      }
      return await askLLMDirect(question, context, env.OPENCODE_API_KEY, model);
    } catch (error) {
      lastError = error;
      if (error instanceof Error && error.message.startsWith("Aucun relais actif")) throw error;
      if (attempt < CALL_MODEL_MAX_RETRIES) await sleep(CALL_MODEL_RETRY_DELAY_MS * (attempt + 1));
    }
  }
  throw lastError;
}

// Above this many documents in one call's context, switch from a single LLM
// call to sequential map-reduce (see generateAnswer). Each document's context
// block is short (bulk text_preview is capped ~420 chars at build time), so
// this batch size stays well within any free model's context window while
// keeping the round-trip count for the common case (most questions retrieve
// far fewer documents than this) at exactly one call, unchanged from before.
const MAP_REDUCE_BATCH_SIZE = 60;

// How many LLM round-trips generateAnswer will make for `hitCount`
// documents -- exported as its own function (not just computed inline
// inside generateAnswer) so handleAsk can announce the total step count to
// the client via a `start` progress event *before* generateAnswer begins
// making calls, letting the progress bar size itself correctly from the
// first event instead of growing/guessing as batches arrive.
function totalAnswerSteps(hitCount: number): number {
  if (hitCount <= MAP_REDUCE_BATCH_SIZE) return 1;
  return Math.ceil(hitCount / MAP_REDUCE_BATCH_SIZE) + 1; // + 1 final synthesis call
}

// Reports one step of progress (1-indexed) out of `totalAnswerSteps(...)`,
// with a short human label for that step. Awaited so the caller (handleAsk)
// can flush it to the client stream before the (potentially slow) LLM call
// for that step actually starts, keeping the bar honestly in sync rather
// than jumping several steps at once.
type ProgressReporter = (step: number, totalSteps: number, label: string) => Promise<void>;

// Everything a client needs to send back, verbatim, to resume a partially
// failed map-reduce answer without redoing the batches that already
// succeeded (see runMapReduceBatches). The Worker itself keeps no session
// state between requests -- this bundle IS the state, round-tripped through
// the client instead of a KV/Durable Object session store.
interface ContinuationBundle {
  query: string;
  model: string;
  profileBlocks: string[];
  degradedNotice?: string;
  remainingHits: SearchHit[];
  remainingDetails: (DocDetail | null)[];
  completedPartials: string[];
  totalSteps: number;
}

interface AnswerResult {
  answer: string;
  // True when one or more batches failed even after callModel's own
  // retries, and this answer was assembled from whatever batches DID
  // succeed rather than the full document set -- see runMapReduceBatches.
  // The caller (runAsk) surfaces this on the `done` event instead of
  // silently presenting a partial answer as a complete one.
  partial: boolean;
  completedSteps: number;
  totalSteps: number;
  failureNote?: string;
  // Present only when partial is true: hand this back as `continuation` in
  // a follow-up /api/ask request (see handleAsk's resume branch) to retry
  // just the failed batch onward, instead of redoing everything.
  continuation?: ContinuationBundle;
}

// Shared core of the map-reduce path, used both for a fresh request (see
// generateAnswer) and to resume one after a partial failure (see
// handleAsk's resume branch / runAsk). `hits`/`details` here are only the
// NOT-YET-PROCESSED documents -- on a fresh request that's everything; on a
// resume it's the remaining batches from where the previous attempt stopped.
// `completedPartials` carries forward any batch notes already produced by
// an earlier attempt so they aren't redone, and `totalSteps` is fixed at the
// very first attempt's document count so the progress bar's denominator
// stays correct across any number of resumes.
//
// If a batch still fails after callModel's internal retries (a real, not
// just transient, problem), the loop stops there rather than throwing away
// every batch that already succeeded: whatever notes exist so far (from
// this attempt AND any earlier ones) are used to produce a best-effort
// partial answer (falling back to the raw notes themselves if even that
// synthesis call fails), clearly flagged via `partial`/`failureNote`/
// `continuation` rather than silently presented as complete or silently
// discarded. Only when NOTHING has succeeded at all does this throw, since
// there is then genuinely no partial progress to preserve or resume from.
async function runMapReduceBatches(
  env: Env,
  query: string,
  model: string,
  profileBlocks: string[],
  degradedNotice: string | undefined,
  hits: SearchHit[],
  details: (DocDetail | null)[],
  onStep: ProgressReporter,
  completedPartials: string[],
  totalSteps: number
): Promise<AnswerResult> {
  const constantBlocks = degradedNotice ? [degradedNotice, ...profileBlocks] : [...profileBlocks];
  const totalBatches = totalSteps - 1; // last step is always the final synthesis call

  const batches: { hits: SearchHit[]; details: (DocDetail | null)[] }[] = [];
  for (let i = 0; i < hits.length; i += MAP_REDUCE_BATCH_SIZE) {
    batches.push({
      hits: hits.slice(i, i + MAP_REDUCE_BATCH_SIZE),
      details: details.slice(i, i + MAP_REDUCE_BATCH_SIZE)
    });
  }

  const partials = [...completedPartials];
  const startStep = completedPartials.length;
  let failureNote: string | undefined;
  let failedBatchIndex = -1;
  for (let i = 0; i < batches.length; i++) {
    const stepNum = startStep + i + 1;
    await onStep(stepNum, totalSteps, `Lot ${stepNum}/${totalBatches}`);
    const batch = batches[i];
    const batchQuestion =
      `Question originale : ${query}\n\n` +
      `Ceci est le lot ${stepNum}/${totalBatches} de documents pertinents pour cette question. Ne réponds PAS de ` +
      "façon définitive et n'invente rien au-delà de ce lot : extrais uniquement, sous forme de notes concises, " +
      "les faits et citations [document_id] de CE lot utiles pour répondre à la question plus tard.";
    const batchContext = [...constantBlocks, buildContext(batch.hits, batch.details)].join("\n\n---\n\n");
    try {
      const partial = await callModel(env, batchQuestion, batchContext, model);
      partials.push(`### Notes du lot ${stepNum}/${totalBatches}\n\n${partial}`);
    } catch (error) {
      failureNote = `échec au lot ${stepNum}/${totalBatches} (${error instanceof Error ? error.message : String(error)})`;
      failedBatchIndex = i;
      break;
    }
  }

  if (failureNote) {
    if (!partials.length) {
      // Nothing succeeded at all, ever -- genuinely no partial progress to
      // preserve or resume from, so this is a real failure.
      throw new Error(`${failureNote} -- aucun lot n'a pu être traité, aucune donnée partielle disponible.`);
    }
    // Includes the FAILED batch again (not just what's after it) so
    // resuming retries it rather than silently dropping those documents --
    // full coverage of the named type is the whole point of the "no cap"
    // retrieval this feeds from.
    const remainingHits = batches.slice(failedBatchIndex).flatMap((b) => b.hits);
    const remainingDetails = batches.slice(failedBatchIndex).flatMap((b) => b.details);
    const continuation: ContinuationBundle = {
      query,
      model,
      profileBlocks,
      degradedNotice,
      remainingHits,
      remainingDetails,
      completedPartials: partials,
      totalSteps
    };
    const partialNotice =
      `### Réponse partielle\n\nUne erreur est survenue en cours de traitement (${failureNote}). Cette réponse ` +
      `se base uniquement sur les ${partials.length}/${totalBatches} lots traités avec succès avant l'erreur -- ` +
      "elle ne couvre pas l'ensemble des documents du type demandé. Indique clairement cette limite dans ta réponse.";
    const reduceQuestion =
      `Question : ${query}\n\n` +
      `Voici des notes préparées à partir de SEULEMENT ${partials.length}/${totalBatches} lots de documents ` +
      "(le reste a échoué -- voir la note de réponse partielle). Synthétise ces notes en UNE réponse cohérente, " +
      "en conservant les citations [document_id] déjà présentes, et en rappelant explicitement que la réponse est " +
      "partielle.";
    const reduceContext = [...constantBlocks, partialNotice, ...partials].join("\n\n---\n\n");
    try {
      const answer = await callModel(env, reduceQuestion, reduceContext, model);
      return { answer, partial: true, completedSteps: partials.length, totalSteps, failureNote, continuation };
    } catch {
      // Even the partial synthesis call failed -- fall back to the raw
      // batch notes themselves rather than nothing at all; still real
      // information extracted from real documents, just unpolished.
      return {
        answer: `${partialNotice}\n\n${partials.join("\n\n")}`,
        partial: true,
        completedSteps: partials.length,
        totalSteps,
        failureNote,
        continuation
      };
    }
  }

  await onStep(totalSteps, totalSteps, "Synthèse finale");
  const reduceQuestion =
    `Question : ${query}\n\n` +
    `Voici des notes préparées à partir de ${totalBatches} lot(s) de documents du corpus. Synthétise-les en UNE ` +
    "réponse finale cohérente et complète, en conservant les citations [document_id] déjà présentes dans les " +
    "notes plutôt qu'en les supprimant.";
  const reduceContext = [...constantBlocks, ...partials].join("\n\n---\n\n");
  try {
    const answer = await callModel(env, reduceQuestion, reduceContext, model);
    return { answer, partial: false, completedSteps: totalSteps, totalSteps };
  } catch (error) {
    // All batches succeeded but the final synthesis call itself failed --
    // still resumable (0 remaining batches, so a "continue" retries just
    // this synthesis step) rather than discarding every batch's notes.
    const failureNoteFinal = `échec lors de la synthèse finale (${error instanceof Error ? error.message : String(error)})`;
    return {
      answer:
        `### Réponse partielle\n\nTous les lots de documents ont été traités avec succès, mais la synthèse finale ` +
        `a échoué (${failureNoteFinal}). Vous pouvez relancer pour ne réessayer que cette étape.`,
      partial: true,
      completedSteps: partials.length,
      totalSteps,
      failureNote: failureNoteFinal,
      continuation: {
        query,
        model,
        profileBlocks,
        degradedNotice,
        remainingHits: [],
        remainingDetails: [],
        completedPartials: partials,
        totalSteps
      }
    };
  }
}

// Produces the final answer for a fully-retrieved set of documents. Below
// MAP_REDUCE_BATCH_SIZE documents, this is exactly the old behaviour: one
// call with the whole context (no continuation possible if it fails -- there
// is no partial progress to speak of for a single call). Above it -- which
// only happens for named types large enough that ALL of their documents (no
// cap, see the retrieval loop in handleAsk) wouldn't fit in one call's
// context window -- this delegates to runMapReduceBatches starting fresh
// (no completed batches yet).
async function generateAnswer(
  env: Env,
  query: string,
  profileBlocks: string[],
  degradedNotice: string | undefined,
  hits: SearchHit[],
  details: (DocDetail | null)[],
  model: string,
  onStep: ProgressReporter
): Promise<AnswerResult> {
  const totalSteps = totalAnswerSteps(hits.length);

  if (hits.length <= MAP_REDUCE_BATCH_SIZE) {
    await onStep(1, totalSteps, "Génération de la réponse");
    const constantBlocks = degradedNotice ? [degradedNotice, ...profileBlocks] : [...profileBlocks];
    const blocks = [...constantBlocks];
    if (hits.length) blocks.push(buildContext(hits, details));
    const answer = await callModel(env, query, blocks.join("\n\n---\n\n"), model);
    return { answer, partial: false, completedSteps: 1, totalSteps };
  }

  return runMapReduceBatches(env, query, model, profileBlocks, degradedNotice, hits, details, onStep, [], totalSteps);
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

// One line of NDJSON (newline-delimited JSON) pushed to the client while
// /api/ask's retrieval + answer generation is still running -- see
// handleAsk's streaming setup below for why (a real, accurate progress bar
// for map-reduce's multiple sequential LLM calls, rather than a fake
// animated one, requires the Worker to actually report progress as it
// happens instead of returning one response at the very end).
type AskEvent =
  | { type: "start"; totalSteps: number }
  | { type: "step"; step: number; totalSteps: number; label: string }
  | {
      type: "done";
      answer: string;
      sources: unknown[];
      browse: unknown[];
      profiles: unknown;
      degraded_notice: string | undefined;
      model: string;
      // Set when a map-reduce batch failed even after retries but earlier
      // batches had already succeeded (see generateAnswer) -- the answer is
      // real, but built from fewer documents than the full named type.
      // Absent (undefined) for a normal, complete answer.
      partial?: boolean;
      completed_steps?: number;
      total_steps?: number;
      failure_note?: string;
      // Present only when partial is true: send this back unchanged as
      // `continuation` in a follow-up POST /api/ask to resume from the
      // failed batch instead of redoing everything (see handleAsk's resume
      // branch). Absent for a normal, complete answer.
      continuation?: ContinuationBundle;
    }
  | {
      type: "error";
      sources: unknown[];
      browse: unknown[];
      profiles: unknown;
      degraded_notice: string | undefined;
      error: string;
    };

// All the retrieval + answer-generation work that used to be handleAsk's
// entire body, before it was wrapped in streaming. Every `return
// Response.json(...)` in the pre-streaming version became an `await
// send(...)` here instead -- same payload shapes, just pushed as one NDJSON
// line rather than the whole HTTP response.
async function runAsk(query: string, model: string, env: Env, origin: string, send: (event: AskEvent) => Promise<void>): Promise<void> {
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
  // Corpus-wide statistical block(s) for whichever type(s) were named --
  // empty for plain/untyped questions. Kept separate (not pre-joined into a
  // single context string) so generateAnswer can re-include it in every
  // batch if map-reduce kicks in, not just a single combined call.
  let profileBlocks: string[];
  // For a named-type question, `browse` is now identical to `hits` (every
  // document of that type, all used in the answer). For the untyped/
  // degraded-compare paths below it's still broader than `hits` -- every
  // document retrieval considered relevant (seeds + graph neighbours, up to
  // BROWSE_LIMIT), not just the smaller subset that fit into the LLM's
  // context -- so a person can still scroll and open anything retrieval
  // considered relevant, not only what the model quoted from.
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
    //
    // No sampling cap here, by design: every document belonging to a named
    // type is fetched and put in context, not a keyword-ranked top-N slice --
    // a purely descriptive question ("caractéristiques d'un memorandum ?")
    // has no discriminating keywords to rank by, so a cap would drop
    // documents arbitrarily rather than meaningfully. A large type (hundreds
    // of documents) is handled by reading previews from the bulk documents
    // index (loadDocumentsIndex, one cached fetch total regardless of type
    // size -- NOT one fetchDocDetail subrequest per document, which would hit
    // Cloudflare Workers' actual subrequest limit for a type like "Autre",
    // 749 documents) and, if the resulting context is still too large for one
    // LLM call, generateAnswer below switches to sequential map-reduce.
    profileBlocks = compareTypes.map((label) => buildProfileBlock(label, docTypeProfiles.types![label]));
    const docsIndex = await loadDocumentsIndex(env, origin);
    const docsIndexById = new Map(docsIndex.map((doc) => [doc.document_id, doc]));
    const seen = new Set<string>();
    hits = [];
    details = [];
    browse = [];
    for (const label of compareTypes) {
      const typedDocs = askDocs.filter((doc) => doc.doc_type === label && !seen.has(doc.id));
      typedDocs.forEach((doc) => seen.add(doc.id));
      const typeHits: SearchHit[] = typedDocs.map((doc) => ({ ...doc, document_id: doc.id, score: 0 }));
      const typeDetails: (DocDetail | null)[] = typeHits.map((hit) => {
        const bulk = docsIndexById.get(hit.document_id);
        if (!bulk) return null;
        return {
          document_id: bulk.document_id,
          title: bulk.title,
          year: bulk.year,
          doc_type: bulk.doc_type,
          treaty_id: hit.treaty_id,
          text_preview: bulk.text_preview
        };
      });
      hits.push(...typeHits);
      details.push(...typeDetails);
      browse.push(...typeHits.map((hit) => ({ ...hit, usedInAnswer: true })));
    }

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
        await send({
          type: "done",
          answer:
            buildUnmatchedTypeClarification(query, compareTypes, docTypeProfiles) ||
            "Aucun document du corpus ne semble correspondre à cette question. Essayez une autre formulation.",
          sources: [],
          browse: [],
          profiles: undefined,
          degraded_notice: undefined,
          model
        });
        return;
      }

      degradedNotice = buildDegradedNotice(compareTypes, docTypeProfiles);
    }
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
      await send({
        type: "done",
        answer: "Aucun document du corpus ne semble correspondre à cette question. Essayez une autre formulation.",
        sources: [],
        browse: [],
        profiles: undefined,
        degraded_notice: undefined,
        model
      });
      return;
    }
    hits = result.hits;
    details = result.details;
    browse = result.browse;
    profileBlocks = [];
  }

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

  // Announce the total step count up front (before any LLM call starts) so
  // the client can size a determinate progress bar immediately rather than
  // guessing or growing it as steps arrive.
  await send({ type: "start", totalSteps: totalAnswerSteps(hits.length) });

  try {
    const result = await generateAnswer(env, query, profileBlocks, degradedNotice, hits, details, model, (step, totalSteps, label) =>
      send({ type: "step", step, totalSteps, label })
    );
    await send({
      type: "done",
      answer: result.answer,
      sources,
      browse: browseSources,
      profiles,
      degraded_notice: degradedNotice,
      model,
      ...(result.partial
        ? {
            partial: true,
            completed_steps: result.completedSteps,
            total_steps: result.totalSteps,
            failure_note: result.failureNote,
            continuation: result.continuation
          }
        : {})
    });
  } catch (error) {
    await send({
      type: "error",
      sources,
      browse: browseSources,
      profiles,
      degraded_notice: degradedNotice,
      error: error instanceof Error ? error.message : String(error)
    });
  }
}

// Resumes a partially-failed map-reduce answer from a client-provided
// ContinuationBundle (see runMapReduceBatches) -- no retrieval, no doc_type
// detection, none of runAsk's usual setup, since all of that already
// happened in the original request and doesn't change on a retry. Only the
// remaining (not-yet-processed) batches get worked on, picking up right
// where the failure occurred instead of starting over from batch 1.
async function runResume(continuation: ContinuationBundle, send: (event: AskEvent) => Promise<void>, env: Env): Promise<void> {
  const model = resolveModel(continuation.model);
  await send({ type: "start", totalSteps: continuation.totalSteps });
  try {
    const result = await runMapReduceBatches(
      env,
      continuation.query,
      model,
      continuation.profileBlocks,
      continuation.degradedNotice,
      continuation.remainingHits,
      continuation.remainingDetails,
      (step, totalSteps, label) => send({ type: "step", step, totalSteps, label }),
      continuation.completedPartials,
      continuation.totalSteps
    );
    // Sources/browse/profiles/degraded_notice are deliberately omitted here
    // (empty/undefined) -- they don't change on a resume, and the client
    // already rendered them from the original response, so there is nothing
    // new to send and no reason to re-fetch or resend potentially large
    // lists (a big named type's browse list can be hundreds of entries).
    await send({
      type: "done",
      answer: result.answer,
      sources: [],
      browse: [],
      profiles: undefined,
      degraded_notice: undefined,
      model,
      ...(result.partial
        ? {
            partial: true,
            completed_steps: result.completedSteps,
            total_steps: result.totalSteps,
            failure_note: result.failureNote,
            continuation: result.continuation
          }
        : {})
    });
  } catch (error) {
    await send({
      type: "error",
      sources: [],
      browse: [],
      profiles: undefined,
      degraded_notice: undefined,
      error: error instanceof Error ? error.message : String(error)
    });
  }
}

// Thin streaming wrapper around runAsk: validates the request body
// synchronously (still a plain 400 JSON response -- nothing to stream yet at
// that point), then hands off to runAsk via ctx.waitUntil, writing each
// event runAsk reports as one NDJSON line to the response body as it
// happens. This is what makes a real (not simulated) progress bar possible
// for map-reduce's multiple sequential LLM calls on large named types (see
// generateAnswer) -- the alternative, a single JSON response at the very
// end, has nothing to show progress against until the whole thing finishes.
async function handleAsk(request: Request, env: Env, origin: string, ctx: ExecutionContextLike): Promise<Response> {
  let query = "";
  let model = DEFAULT_MODEL;
  let continuation: ContinuationBundle | undefined;
  try {
    const body = (await request.json()) as { query?: string; model?: string; continuation?: ContinuationBundle };
    // A "continue" request from the client (see runResume/ContinuationBundle)
    // -- resumes a previously partial map-reduce answer instead of asking a
    // brand new question, so `query`/`model` come from the bundle itself
    // rather than the top-level body fields.
    if (body.continuation && Array.isArray(body.continuation.remainingHits)) {
      continuation = body.continuation;
    } else {
      query = (body.query || "").trim();
      model = resolveModel(body.model);
    }
  } catch {
    return Response.json({ error: "Corps de requête JSON invalide." }, { status: 400 });
  }
  if (!continuation && !query) {
    return Response.json({ error: "Question vide." }, { status: 400 });
  }

  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const encoder = new TextEncoder();
  const send = (event: AskEvent) => writer.write(encoder.encode(JSON.stringify(event) + "\n"));

  ctx.waitUntil(
    (async () => {
      try {
        if (continuation) {
          await runResume(continuation, send, env);
        } else {
          await runAsk(query, model, env, origin, send);
        }
      } catch (error) {
        // Only reached if runAsk itself threw outside its own try/catch
        // (e.g. loadAskIndex failing) -- runAsk's own retrieval/answer
        // errors are already turned into a "error" event above.
        await send({
          type: "error",
          sources: [],
          browse: [],
          profiles: undefined,
          degraded_notice: undefined,
          error: error instanceof Error ? error.message : String(error)
        }).catch(() => undefined);
      } finally {
        await writer.close().catch(() => undefined);
      }
    })()
  );

  return new Response(readable, {
    headers: { "Content-Type": "application/x-ndjson; charset=utf-8", "Cache-Control": "no-store" }
  });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContextLike): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/ask") {
      if (request.method !== "POST") {
        return new Response("Method Not Allowed", { status: 405 });
      }
      return handleAsk(request, env, url.origin, ctx);
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
