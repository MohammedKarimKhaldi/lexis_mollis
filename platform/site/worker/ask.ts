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
const API_MODEL = "big-pickle";
const MAX_HITS = 6;
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
  "types de documents sur les statistiques qu'elles donnent (fractions de documents, moyennes) et " +
  "cite les pourcentages exacts plutôt que des impressions générales ; illustre avec les extraits " +
  "réels fournis.";

// Mirrors the keys of metadata_design/doc_type_mapping.json (kept in sync by hand —
// it changes rarely; see PROJECT_STATUS.md if it drifts).
const DOC_TYPE_LABELS = [
  "Accord", "Arrangement", "Autre", "Certificat", "Convention", "Déclaration",
  "Échange de lettres", "Inconnu", "Instrument d'adhésion", "Instrument de ratification",
  "Lettre", "Minutes", "Note verbale", "Notification", "Pouvoirs", "Procès-verbal",
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
    const lines = [
      `### [${hit.document_id}] ${title} (${detail?.year ?? hit.year ?? "année n/a"}, score=${hit.score.toFixed(2)})`,
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

async function askLLMDirect(question: string, context: string, apiKey: string): Promise<string> {
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
      model: API_MODEL,
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

// Preferred path — see module header comment. `relayUrl` is the full /ask URL
// of scripts/llm_relay.py, exposed through a Cloudflare Tunnel. The relay adds
// the SYSTEM_PROMPT and calls OpenCode Zen itself (from a residential IP), so
// only the raw question + context need to travel over the tunnel.
async function askLLMViaRelay(question: string, context: string, relayUrl: string, sharedSecret: string): Promise<string> {
  const response = await fetch(relayUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Relay-Secret": sharedSecret },
    body: JSON.stringify({ question, context })
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Relay ${response.status}: ${body.slice(0, 300)}`);
  }
  const data = (await response.json()) as { answer?: string; error?: string };
  if (data.error) throw new Error(data.error);
  return data.answer ?? "";
}

async function handleAsk(request: Request, env: Env, origin: string): Promise<Response> {
  let query = "";
  try {
    const body = (await request.json()) as { query?: string };
    query = (body.query || "").trim();
  } catch {
    return Response.json({ error: "Corps de requête JSON invalide." }, { status: 400 });
  }
  if (!query) {
    return Response.json({ error: "Question vide." }, { status: 400 });
  }

  const askDocs = await loadAskIndex(env, origin);
  const docTypeProfiles = await loadDocTypeProfiles(env, origin);
  const compareTypes = detectDocTypes(query, DOC_TYPE_LABELS).filter((label) => docTypeProfiles.types?.[label]);

  let hits: SearchHit[];
  let contextBlocks: string[];

  if (compareTypes.length >= 2) {
    // Comparison mode: prepend corpus-wide structural profiles for each named
    // type, then retrieve real excerpts *per type* (not one undifferentiated
    // top-k) so under-represented types aren't crowded out — see the module
    // header comment and scripts/rag_ask.py for the equivalent local logic.
    const profileBlocks = compareTypes.map((label) => buildProfileBlock(label, docTypeProfiles.types![label]));
    const perType = Math.max(1, Math.floor(MAX_HITS / compareTypes.length));
    const seen = new Set<string>();
    hits = [];
    for (const label of compareTypes) {
      const typedDocs = askDocs.filter((doc) => doc.doc_type === label);
      for (const hit of searchAskIndex(query, typedDocs, perType)) {
        if (seen.has(hit.document_id)) continue;
        seen.add(hit.document_id);
        hits.push(hit);
      }
    }
    const details = await Promise.all(hits.map((hit) => fetchDocDetail(env, origin, hit.document_id)));
    contextBlocks = [...profileBlocks];
    if (hits.length) contextBlocks.push(buildContext(hits, details));
  } else {
    hits = searchAskIndex(query, askDocs, MAX_HITS);
    if (!hits.length) {
      return Response.json({
        answer: "Aucun document du corpus ne semble correspondre à cette question. Essayez une autre formulation.",
        sources: []
      });
    }
    const details = await Promise.all(hits.map((hit) => fetchDocDetail(env, origin, hit.document_id)));
    contextBlocks = [buildContext(hits, details)];
  }

  const context = contextBlocks.join("\n\n---\n\n");
  const sources = hits.map((hit) => ({
    document_id: hit.document_id,
    title: hit.title,
    year: hit.year,
    score: hit.score
  }));

  const relayUrl = (await getActiveRelayUrl(env)) || env.RELAY_URL;
  if (relayUrl && env.RELAY_SHARED_SECRET) {
    try {
      const answer = await askLLMViaRelay(query, context, relayUrl, env.RELAY_SHARED_SECRET);
      return Response.json({ answer, sources });
    } catch (error) {
      return Response.json(
        { answer: null, sources, error: error instanceof Error ? error.message : String(error) },
        { status: 502 }
      );
    }
  }

  if (!env.OPENCODE_API_KEY) {
    return Response.json({
      answer: null,
      sources,
      error:
        "Aucun relais actif (voir scripts/run_relay_stack.sh) et OPENCODE_API_KEY n'est pas non " +
        "plus configuré côté serveur (wrangler secret put ...)."
    });
  }

  try {
    const answer = await askLLMDirect(query, context, env.OPENCODE_API_KEY);
    return Response.json({ answer, sources });
  } catch (error) {
    return Response.json(
      { answer: null, sources, error: error instanceof Error ? error.message : String(error) },
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
    return env.ASSETS.fetch(request);
  }
};
