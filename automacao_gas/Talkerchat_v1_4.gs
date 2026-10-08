/***********************
 *  TALKERCHAT API → MySQL (alex_talkerchat_api)
 *  Projeto: "Ad Sources to DB"   ·   arquivo: Talkerchat.gs   ·   v1.4.1 (05/10/2026)
 *  v1.4.1: UPDATE do CPF por telefone_key (indexado) — o v1.4 filtrava só por `telefone` e varria a tabela a cada UPDATE.
 *  v1.4 (05/10): CPF pelo OBJETO DE CONTATO da API + todos os motivos + backfill controlado por Script Properties.
 *        (a) A documentação (painel → API) ganhou rotas fora do /public: GET /contact-object/{telefone}/values devolve
 *            o objeto "Dados pessoais" do contato (campos cpf, cep, nome, email, telefone, qualificacao) e o objeto
 *            "Infos Hubspot" — conferido em 05/10 com o token BI_Growth: 200, CPF preenchido inclusive para contatos
 *            barrados na triagem. É 1 chamada por TELEFONE (vale para todos os tickets daquele número), estruturada,
 *            sem depender de o cliente ter digitado só o CPF. Passa a ser a fonte principal (cpf_source='contact');
 *            /tickets/{id}/messages continua como fallback por ticket (cpf_source='messages') quando o objeto está vazio.
 *            Também existe GET /close-reasons (isConversion por motivo). Etiquetas continuam só de escrita (add-tag).
 *        (b) CPF_REASONS=[] → TODOS os motivos. Antes só 4 motivos (Compra reportada, CPF já Cadastrado, Link enviado,
 *            Transferido para SAC) eram enriquecidos — as conversas da Lia fechadas por "Fim de expediente", "Sem
 *            Interação", "Inatividade", "Finalizado após encerrar janela" (≈ 75 k tickets/mês) e o "Redirecionado para
 *            o SAC" da fila Triagem (nova desde 29/09) ficavam sem CPF, e o "qualificado = CPF validado como não cliente"
 *            do dashboard virava piso. Filas de NPS fora (CPF_SKIP_QUEUES); prioridade para os motivos de venda
 *            (CPF_PRIORITY_REASONS); dentro do mesmo motivo, os mais recentes primeiro.
 *        (c) Backfill do histórico (abr/26 em diante — nada antes de ago/26 foi enriquecido, nem os motivos antigos):
 *            rodar tkcCpfBackfill("2026-04-16", true) no editor → grava TKC_CPF_SINCE (+ TKC_CPF_SKIP_SAC=1 para pular
 *            SAC/já cadastrado no histórico); o worker consome CPF_MAX_PER_RUN chamadas por execução até zerar e então
 *            apaga as propriedades sozinho (volta à janela de CPF_DAYS_BACK). tkcCpfBackfillStatus() mostra o que falta.
 *            Como o objeto de contato cobre todos os tickets do telefone, o backlog cai bem mais rápido que 1:1.
 *            Para acelerar: tkcInstalarTriggers() com WORKER_MINUTES=10 durante o backfill (144 execuções × 500 =
 *            72 k chamadas/dia; cota UrlFetch do Workspace = 100 k/dia, Gmail = 20 k/dia) e voltar a 30 depois.
 *  v1.3: cadência do worker. Depois que o backfill fechou (19/09) o trabalho diário cabe em ~10 execuções
 *        (tkcDaily 6h → tickets até ~07h; CPF por mensagens até ~10h) e as outras ~130 execuções/dia do
 *        trigger de 10 min só liam a fila vazia. WORKER_MINUTES=30 (48 execuções/dia) e CPF_MAX_PER_RUN=500
 *        (mesmo throughput de CPF: ~0,5 s por chamada, cabe no BUDGET_MS). Instalar: colar → tkcInstalarTriggers().
 *        Saúde_Config linha 48 (heartbeat TKC_LAST_RUN): regra min:30 → min:75 (saude_rotinas.gs v1.9).
 *  v1.2: INSERT em fatias de CHUNK_ROWS linhas (400 linhas num statement só deu
 *        "Argument too large: sql" no JDBC do Apps Script — limite ~64 KB por statement).
 *  v1.1: upsert por INSERT multi-linha em string (o prepared statement + addBatch do JDBC do
 *        Apps Script custa ~1 RPC por setString → 20 s por página; agora ~0,2 s), buffer de
 *        BUFFER_ROWS linhas entre flushes, checkpoint da fila só depois do flush.
 *
 *  Substitui o export/import manual de CSV do Talkerchat. Lê /public/tickets da
 *  API pública (https://service.talkerchat.com.br) e faz UPSERT em
 *  `alex_talkerchat_api` (tabela criada automaticamente na 1ª conexão;
 *  view compatível + queries de validação em talkerchat_api.sql).
 *
 *  Desenho
 *   - Fila de jobs em Script Properties (TKC_JOBS): cada job = janela de 1 dia
 *     de um dateField (createdAt | closedAt | updatedAt) + página atual.
 *   - tkcWorker() roda a cada WORKER_MINUTES, pega a fila e trabalha ~4,5 min
 *     (limite de 6 min do Apps Script), gravando a página em que parou.
 *     Fila vazia = sai em <1 s.
 *   - tkcDaily() (trigger diário, 6h) enfileira as janelas dos últimos
 *     LOOKBACK_DAYS dias nos 3 dateFields: createdAt pega tickets novos,
 *     closedAt pega encerramentos (updatedAt NÃO é atualizado no close —
 *     verificado 15/09), updatedAt pega mudanças de motivo/fila/agente.
 *   - tkcBackfillTudo() enfileira createdAt dia a dia desde 16/04/2026
 *     (início do histórico na API; jan–15/abr retorna 0).
 *   - tkcCpfEnrich_(): /public/tickets não traz CPF nem etiquetas (reconferido em
 *     05/10/2026: só id, status, channel, attendedByBot, contact{id,name,identification},
 *     queue, agent, closeReason, datas). O CPF vem (1) do objeto de contato
 *     GET /contact-object/{telefone}/values (campo cpf de "Dados pessoais"; 1 chamada por
 *     telefone, aplicada a todos os tickets do número ainda sem CPF) e, se vazio,
 *     (2) de /tickets/{id}/messages — primeira mensagem inbound com exatamente 11
 *     dígitos (teste 22/08: 26/30 recuperados, 0 errados). Roda dentro do worker,
 *     depois dos jobs de tickets, limitado por CPF_MAX_PER_RUN chamadas.
 *
 *  Fusos: a API devolve timestamps em UTC ("...Z") mas filtra dateStart/
 *  dateEnd em horário de Brasília. Gravamos tudo convertido para
 *  America/Sao_Paulo. (Atenção: o CSV manual/alex_talkerchat gravou UTC como
 *  se fosse local — 3 h de deslocamento em relação a esta tabela.)
 *
 *  Script Properties: DB_URL, DB_USER, DB_PASS (já existem) + TALKERCHAT_TOKEN.
 *  Volume: ~6–9k tickets/dia → ~350–450 páginas de 20 por janela; ~0,5 s/chamada.
 *  Cota UrlFetch do Apps Script: 20k/dia (Gmail) ou 100k/dia (Workspace).
 ***********************/

const TKC = {
  BASE: "https://service.talkerchat.com.br/public",
  TZ: "America/Sao_Paulo",
  TABLE: "alex_talkerchat_api",
  PAGE_LIMIT: 20,              // máximo aceito pela API
  LOOKBACK_DAYS: 2,            // tkcDaily: janelas D-2..D
  BACKFILL_FROM: "2026-04-16", // primeiro dia com tickets na API
  BUDGET_MS: 4.5 * 60 * 1000,  // tempo de trabalho por execução do worker
  WORKER_MINUTES: 30,          // v1.3: intervalo do trigger tkcWorker (era 10; valores aceitos: 1,5,10,15,30). 10 durante um backfill de CPF.
  BUFFER_ROWS: 400,            // linhas acumuladas antes de gravar (20 páginas)
  CHUNK_ROWS: 100,             // linhas por INSERT (≈30 KB; o JDBC recusa statements grandes)
  HTTP_RETRIES: 4,
  CPF_ENRICH: true,            // false = não gasta chamadas em /messages
  CPF_MAX_PER_RUN: 500,        // chamadas HTTP (contact-object + messages) por execução do worker (~0,5 s cada = o BUDGET_MS)
  CPF_OBJECT: "dados_pessoais", // v1.4: objeto de contato que guarda o CPF (campo identifier 'cpf'); "" = pular o objeto e usar só mensagens
  CPF_DAYS_BACK: 45,           // rotina: só enriquece tickets criados nos últimos N dias (o backfill ignora, ver TKC_CPF_SINCE)
  // v1.4: [] = TODOS os motivos (antes: só Compra reportada / CPF já Cadastrado / Link enviado / Transferido para SAC).
  CPF_REASONS: [],
  // v1.4: motivos atendidos primeiro dentro de cada execução (os de venda/qualificação); depois, os demais — sempre mais recentes primeiro.
  CPF_PRIORITY_REASONS: ["Compra reportada", "Link enviado", "CPF já Cadastrado", "Transferido para SAC", "Redirecionado para o SAC"],
  // v1.4: filas sem valor de CPF para o funil (pesquisa de NPS) — não gastam chamada.
  CPF_SKIP_QUEUES: ["SAC Coleta NPS"],
  // v1.4: motivos "já é cliente" (SAC / CPF já Cadastrado) — pulados no backfill quando TKC_CPF_SKIP_SAC=1
  CPF_SAC_REASON_IDS: [4, 174, 186, 5],
  PROP_JOBS: "TKC_JOBS",
  PROP_LAST: "TKC_LAST_RUN",
  PROP_CPF_SINCE: "TKC_CPF_SINCE",       // v1.4: AAAA-MM-DD → backfill de CPF a partir desta data (apagada ao terminar)
  PROP_CPF_SKIP_SAC: "TKC_CPF_SKIP_SAC", // v1.4: "1" → o backfill pula os motivos de SAC/já cadastrado
};

/* ------------------------------------------------------------------ */
/*  Entradas (triggers / manuais)                                      */
/* ------------------------------------------------------------------ */

/** Trigger diário (6h): enfileira as janelas incrementais. */
function tkcDaily() {
  const today = tkcFmtDate_(new Date());
  const start = tkcFmtDate_(tkcAddDays_(new Date(), -TKC.LOOKBACK_DAYS));
  const jobs = tkcLoadJobs_();
  ["createdAt", "closedAt", "updatedAt"].forEach(function (f) {
    tkcEnqueueDays_(jobs, f, start, today, true);   // na frente: o incremental não espera o backfill
  });
  tkcSaveJobs_(jobs);
  Logger.log("tkcDaily: fila com %s jobs (%s..%s)", jobs.length, start, today);
}

/** Trigger a cada WORKER_MINUTES: consome a fila com orçamento de tempo. */
function tkcWorker() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) { Logger.log("tkcWorker: outro worker ativo, saindo."); return; }
  const t0 = Date.now();
  let conn = null, pages = 0, rows = 0, cpfs = 0;
  try {
    const jobs = tkcLoadJobs_();
    if (jobs.length === 0 && !TKC.CPF_ENRICH) { Logger.log("tkcWorker: fila vazia."); return; }
    conn = tkcConn_();
    const token = tkcToken_();

    let buffer = [];
    const flush = function () {                        // grava o buffer e SÓ ENTÃO salva a fila
      if (buffer.length > 0) { rows += tkcUpsertTickets_(conn, buffer); buffer = []; }
      tkcSaveJobs_(jobs);
    };
    while (jobs.length > 0 && Date.now() - t0 < TKC.BUDGET_MS) {
      const job = jobs[0];
      const res = tkcFetchTickets_(token, job.field, job.start, job.end, job.page);
      Array.prototype.push.apply(buffer, res.data);
      pages++;
      job.totalPages = res.pagination.totalPages;
      if (job.page >= job.totalPages || res.data.length === 0) {
        jobs.shift();                                  // job concluído
      } else {
        job.page++;
      }
      if (buffer.length >= TKC.BUFFER_ROWS) flush();
    }
    flush();

    if (TKC.CPF_ENRICH && jobs.length === 0 && Date.now() - t0 < TKC.BUDGET_MS) {
      cpfs = tkcCpfEnrich_(conn, token, t0);
    }
    PropertiesService.getScriptProperties().setProperty(TKC.PROP_LAST,
      Utilities.formatDate(new Date(), TKC.TZ, "yyyy-MM-dd HH:mm:ss") +
      " pages=" + pages + " rows=" + rows + " cpf=" + cpfs + " fila=" + jobs.length);
    Logger.log("tkcWorker: %s páginas, %s linhas upsert, %s CPFs, %s jobs restantes, %ss",
      pages, rows, cpfs, jobs.length, Math.round((Date.now() - t0) / 1000));
  } finally {
    if (conn) try { conn.close(); } catch (e) {}
    lock.releaseLock();
  }
}

/** Backfill completo do histórico (createdAt, dia a dia). Sem parâmetros de propósito. */
function tkcBackfillTudo() {
  tkcBackfill(TKC.BACKFILL_FROM, tkcFmtDate_(tkcAddDays_(new Date(), -1)));
}

/** Backfill de um intervalo (AAAA-MM-DD). Ex.: tkcBackfill("2026-08-16","2026-08-18") para o buraco do CSV. */
function tkcBackfill(from, to) {
  if (!from || !to) throw new Error("Use tkcBackfillTudo() ou chame tkcBackfill('AAAA-MM-DD','AAAA-MM-DD') pelo editor.");
  const jobs = tkcLoadJobs_();
  tkcEnqueueDays_(jobs, "createdAt", from, to);
  tkcSaveJobs_(jobs);
  Logger.log("tkcBackfill: %s..%s enfileirado; fila com %s jobs. O tkcWorker consome ~450 páginas por execução.", from, to, jobs.length);
}

/** Atalho sem parâmetros: só o que falta desde o fim do CSV (01/09) + buraco 16–18/08. */
function tkcBackfillDesdeSetembro() {
  tkcBackfill("2026-08-16", "2026-08-18");
  tkcBackfill("2026-09-01", tkcFmtDate_(tkcAddDays_(new Date(), -1)));
}

/** v1.4 — Backfill de CPF: liga o modo "desde <data>" no tkcCpfEnrich_ (o worker consome CPF_MAX_PER_RUN por execução
 *  até zerar e então apaga as propriedades). skipSac=true pula os motivos de SAC / CPF já Cadastrado no histórico
 *  (≈ 230 k tickets abr–set que não entram no funil "sem SAC"). Sem parâmetros = desde 16/04/2026, pulando SAC. */
function tkcCpfBackfill(since, skipSac) {
  since = since || TKC.BACKFILL_FROM;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(since)) throw new Error("tkcCpfBackfill('AAAA-MM-DD', true|false)");
  if (skipSac === undefined) skipSac = true;
  const props = PropertiesService.getScriptProperties();
  props.setProperty(TKC.PROP_CPF_SINCE, since);
  if (skipSac) props.setProperty(TKC.PROP_CPF_SKIP_SAC, "1"); else props.deleteProperty(TKC.PROP_CPF_SKIP_SAC);
  Logger.log("tkcCpfBackfill: ligado desde %s (pular SAC: %s). Acompanhe com tkcCpfBackfillStatus().", since, skipSac);
  tkcCpfBackfillStatus();
}

/** v1.4 — Quantos tickets ainda serão verificados no modo atual (backfill ou rotina). */
function tkcCpfBackfillStatus() {
  const props = PropertiesService.getScriptProperties();
  const since = props.getProperty(TKC.PROP_CPF_SINCE);
  Logger.log("Modo: %s · pular SAC: %s", since ? "backfill desde " + since : "rotina (" + TKC.CPF_DAYS_BACK + " dias)",
    props.getProperty(TKC.PROP_CPF_SKIP_SAC) === "1");
  const conn = tkcConn_();
  try {
    const rs = conn.createStatement().executeQuery("SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM " + TKC.TABLE + tkcCpfWhere_(props));
    if (rs.next()) Logger.log("A verificar: %s tickets (criados %s → %s) · %s por execução do worker, %s execuções/dia",
      rs.getString(1), rs.getString(2), rs.getString(3), TKC.CPF_MAX_PER_RUN, Math.floor(1440 / TKC.WORKER_MINUTES));
    rs.close();
  } finally { conn.close(); }
}

/** v1.4 — Desliga o backfill de CPF (volta à janela de CPF_DAYS_BACK). */
function tkcCpfBackfillParar() {
  const props = PropertiesService.getScriptProperties();
  props.deleteProperty(TKC.PROP_CPF_SINCE);
  props.deleteProperty(TKC.PROP_CPF_SKIP_SAC);
  Logger.log("Backfill de CPF desligado.");
}

/** Mostra fila, última execução e frescor da tabela. */
function tkcStatus() {
  const props = PropertiesService.getScriptProperties();
  const jobs = tkcLoadJobs_();
  Logger.log("Última execução: %s", props.getProperty(TKC.PROP_LAST) || "(nunca)");
  Logger.log("Fila (%s): %s", jobs.length, JSON.stringify(jobs.slice(0, 5)));
  const conn = tkcConn_();
  try {
    const rs = conn.createStatement().executeQuery(
      "SELECT COUNT(*), MIN(created_at), MAX(created_at), MAX(loaded_at), SUM(cpf IS NOT NULL), SUM(status<>'closed') FROM " + TKC.TABLE);
    if (rs.next()) Logger.log("Tabela: %s linhas · created %s → %s · loaded_at %s · com CPF %s · não encerrados %s",
      rs.getString(1), rs.getString(2), rs.getString(3), rs.getString(4), rs.getString(5), rs.getString(6));
    rs.close();
  } finally { conn.close(); }
}

/** Limpa a fila (se algo travar). */
function tkcResetFila() {
  PropertiesService.getScriptProperties().deleteProperty(TKC.PROP_JOBS);
  Logger.log("Fila limpa.");
}

/** Cria os triggers (rodar uma vez). */
function tkcInstalarTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (["tkcWorker", "tkcDaily"].indexOf(t.getHandlerFunction()) !== -1) ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger("tkcDaily").timeBased().everyDays(1).atHour(6).inTimezone(TKC.TZ).create();
  ScriptApp.newTrigger("tkcWorker").timeBased().everyMinutes(TKC.WORKER_MINUTES).create();
  Logger.log("Triggers criados: tkcDaily 6h · tkcWorker a cada " + TKC.WORKER_MINUTES + " min.");
}

/** Teste rápido de autenticação + 1 página. */
function tkcTeste() {
  const token = tkcToken_();
  const d = tkcFmtDate_(tkcAddDays_(new Date(), -1));
  const res = tkcFetchTickets_(token, "createdAt", d, d, 1);
  Logger.log("ontem (%s): total=%s totalPages=%s · exemplo: %s", d, res.pagination.total, res.pagination.totalPages, JSON.stringify(res.data[0]));
}

/* ------------------------------------------------------------------ */
/*  API                                                                */
/* ------------------------------------------------------------------ */

function tkcToken_() {
  const t = PropertiesService.getScriptProperties().getProperty("TALKERCHAT_TOKEN");
  if (!t) throw new Error("❌ TALKERCHAT_TOKEN não encontrado em Script Properties.");
  return t;
}

function tkcFetchTickets_(token, field, start, end, page) {
  const url = TKC.BASE + "/tickets?dateField=" + field + "&dateStart=" + start + "&dateEnd=" + end +
    "&order=asc&page=" + page + "&limit=" + TKC.PAGE_LIMIT;
  return tkcGetJson_(token, url);
}

function tkcFetchMessages_(token, ticketId) {
  return tkcGetJson_(token, TKC.BASE + "/tickets/" + ticketId + "/messages?page=1&limit=20&order=asc");
}

/** v1.4 — Objeto de contato (rota fora do /public): CPF estruturado do telefone, ou null se não preenchido. */
function tkcFetchContactCpf_(token, telefone) {
  const base = TKC.BASE.replace(/\/public$/, "");
  const r = tkcGetJson_(token, base + "/contact-object/" + encodeURIComponent(telefone) + "/values?objectIdentifier=" + TKC.CPF_OBJECT);
  const objs = (r && r.objects) || [];
  for (let i = 0; i < objs.length; i++) {
    const fields = objs[i].fields || [];
    for (let j = 0; j < fields.length; j++) {
      if (fields[j].identifier !== "cpf" || !fields[j].value) continue;
      const digits = String(fields[j].value).replace(/\D/g, "");
      if (digits.length === 11 && !/^(\d)\1{10}$/.test(digits)) return digits;
    }
  }
  return null;
}

function tkcGetJson_(token, url) {
  let lastErr = null;
  for (let i = 0; i < TKC.HTTP_RETRIES; i++) {
    try {
      const resp = UrlFetchApp.fetch(url, {
        method: "get", muteHttpExceptions: true,
        headers: { Authorization: "Bearer " + token, Accept: "application/json" },
      });
      const code = resp.getResponseCode();
      if (code === 200) return JSON.parse(resp.getContentText());
      if (code === 401) throw new Error("401 token inválido/revogado");
      if (code === 404) return { data: [], pagination: { page: 1, totalPages: 1, total: 0 } };
      lastErr = new Error("HTTP " + code + " " + resp.getContentText().slice(0, 200));
    } catch (e) {
      if (String(e.message).indexOf("401") === 0) throw e;
      lastErr = e;
    }
    Utilities.sleep(1500 * (i + 1));
  }
  throw new Error("Talkerchat falhou após retries: " + url + " → " + lastErr);
}

/* ------------------------------------------------------------------ */
/*  MySQL                                                              */
/* ------------------------------------------------------------------ */

const TKC_COLS = [
  "id", "status", "channel", "attended_by_bot",
  "contact_id", "contact_name", "telefone", "telefone_key",
  "queue_id", "queue", "agent_id", "agent", "agent_email",
  "close_reason_id", "close_reason",
  "created_at", "opened_at", "closed_at", "updated_at",
];

function tkcUpsertTickets_(conn, tickets) {
  // Um único INSERT multi-linha com literais escapados: no JDBC do Apps Script cada
  // setString/addBatch é uma chamada remota (~50 ms) — 20 linhas × 19 colunas = 20 s/página.
  const updates = TKC_COLS.filter(function (c) { return c !== "id"; })
    .map(function (c) { return c + "=VALUES(" + c + ")"; }).join(",") + ",loaded_at=NOW()";
  const head = "INSERT INTO " + TKC.TABLE + " (" + TKC_COLS.join(",") + ",loaded_at) VALUES ";
  const seen = {};
  const values = [];
  tickets.forEach(function (t) {                        // dedupe por id dentro do lote (janelas de createdAt/closedAt/updatedAt se sobrepõem)
    if (seen[t.id]) return;
    seen[t.id] = true;
    values.push("(" + tkcTicketRow_(t).map(tkcLit_).join(",") + ",NOW())");
  });
  if (values.length === 0) return 0;
  const stmt = conn.createStatement();
  try {
    let n = 0;
    for (let i = 0; i < values.length; i += TKC.CHUNK_ROWS) {   // fatias: "Argument too large: sql" acima de ~64 KB
      const sql = head + values.slice(i, i + TKC.CHUNK_ROWS).join(",") + " ON DUPLICATE KEY UPDATE " + updates;
      stmt.execute(sql);
      n += Math.min(TKC.CHUNK_ROWS, values.length - i);
    }
    return n;
  } finally { stmt.close(); }
}

/** Literal SQL: NULL, número ou string escapada (\\, ', quebras de linha, NUL). */
function tkcLit_(v) {
  if (v === null || v === undefined || v === "") return "NULL";
  if (typeof v === "number") return String(v);
  return "'" + String(v).replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/\x00/g, "").replace(/\r?\n/g, " ") + "'";
}

function tkcTicketRow_(t) {
  const c = t.contact || {}, q = t.queue || {}, a = t.agent || {}, cr = t.closeReason || {};
  const tel = c.identification ? String(c.identification).replace(/\D/g, "") : null;
  return [
    t.id, t.status, t.channel, t.attendedByBot ? 1 : 0,
    c.id, c.name, tel, tel && tel.length >= 8 ? tel.slice(-8) : null,
    q.id, q.name, a.id, a.name, a.email,
    cr.id, cr.title,
    tkcIsoToLocal_(t.createdAt), tkcIsoToLocal_(t.openedAt), tkcIsoToLocal_(t.closedAt), tkcIsoToLocal_(t.updatedAt),
  ];
}

/* ------------------------------------------------------------------ */
/*  CPF via mensagens                                                  */
/* ------------------------------------------------------------------ */

/** v1.4 — WHERE do enriquecimento (rotina ou backfill), compartilhado por tkcCpfEnrich_ e tkcCpfBackfillStatus. */
function tkcCpfWhere_(props) {
  const lit = function (s) { return "'" + String(s).replace(/'/g, "''") + "'"; };
  const since = props.getProperty(TKC.PROP_CPF_SINCE);
  let w = " WHERE cpf IS NULL AND msgs_checked_at IS NULL AND status='closed'";
  w += since ? " AND created_at >= " + lit(since)
             : " AND created_at >= DATE_SUB(NOW(), INTERVAL " + TKC.CPF_DAYS_BACK + " DAY)";
  if (TKC.CPF_REASONS.length) w += " AND close_reason IN (" + TKC.CPF_REASONS.map(lit).join(",") + ")";
  if (TKC.CPF_SKIP_QUEUES.length) w += " AND COALESCE(queue,'') NOT IN (" + TKC.CPF_SKIP_QUEUES.map(lit).join(",") + ")";
  if (since && props.getProperty(TKC.PROP_CPF_SKIP_SAC) === "1" && TKC.CPF_SAC_REASON_IDS.length) {
    w += " AND COALESCE(close_reason_id, 0) NOT IN (" + TKC.CPF_SAC_REASON_IDS.join(",") + ")";
  }
  return w;
}

function tkcCpfEnrich_(conn, token, t0) {
  const props = PropertiesService.getScriptProperties();
  const lit = function (s) { return "'" + String(s).replace(/'/g, "''") + "'"; };
  const prio = TKC.CPF_PRIORITY_REASONS.length
    ? "(close_reason IN (" + TKC.CPF_PRIORITY_REASONS.map(lit).join(",") + ")) DESC, " : "";
  const rs = conn.createStatement().executeQuery(
    "SELECT id, telefone FROM " + TKC.TABLE + tkcCpfWhere_(props) +
    " ORDER BY " + prio + "created_at DESC LIMIT " + TKC.CPF_MAX_PER_RUN);
  const ids = [], tels = {};
  while (rs.next()) { ids.push(rs.getString(1)); tels[rs.getString(1)] = rs.getString(2); }
  rs.close();
  if (ids.length === 0) {
    if (props.getProperty(TKC.PROP_CPF_SINCE)) {        // v1.4: backfill terminou → volta à rotina sozinho
      props.deleteProperty(TKC.PROP_CPF_SINCE);
      props.deleteProperty(TKC.PROP_CPF_SKIP_SAC);
      Logger.log("tkcCpfEnrich: backfill de CPF concluído — voltando à janela de %s dias.", TKC.CPF_DAYS_BACK);
    }
    return 0;
  }

  // grava em lotes de 50 com um INSERT ... ON DUPLICATE KEY UPDATE só das colunas de CPF
  // (1 statement por lote; os ids já existem na tabela, então é só UPDATE na prática)
  const stmt = conn.createStatement();
  let found = 0, done = 0, calls = 0, viaContato = 0, lote = [];
  const cache = {};                                     // telefone → cpf (ou null) já consultado nesta execução
  const flushCpf = function () {
    if (lote.length === 0) return;
    stmt.execute("INSERT INTO " + TKC.TABLE + " (id,cpf,cpf_source,msgs_total,msgs_checked_at) VALUES " + lote.join(",") +
      " ON DUPLICATE KEY UPDATE cpf=VALUES(cpf), cpf_source=VALUES(cpf_source), msgs_total=VALUES(msgs_total), msgs_checked_at=NOW()");
    lote = [];
  };
  try {
    for (let i = 0; i < ids.length && calls < TKC.CPF_MAX_PER_RUN && Date.now() - t0 < TKC.BUDGET_MS; i++) {
      const id = ids[i], tel = tels[id];
      // (1) objeto de contato — 1 chamada por telefone; o CPF vale para todos os tickets do número ainda sem CPF
      if (TKC.CPF_OBJECT && tel && !(tel in cache)) {
        cache[tel] = tkcFetchContactCpf_(token, tel); calls++;
        if (cache[tel]) {
          // telefone_key (tel-8) primeiro: é a coluna indexada (ix_tel8); só "telefone=" varria a tabela inteira (~1 s por UPDATE)
          stmt.execute("UPDATE " + TKC.TABLE + " SET cpf=" + tkcLit_(cache[tel]) + ", cpf_source='contact', msgs_checked_at=NOW()" +
            " WHERE telefone_key=" + tkcLit_(tel.slice(-8)) + " AND telefone=" + tkcLit_(tel) + " AND cpf IS NULL");
          viaContato++;
        }
      }
      if (tel && cache[tel]) { found++; done++; continue; }   // já gravado pelo UPDATE acima (inclusive este id)
      // (2) fallback: mensagens do ticket
      const m = tkcFetchMessages_(token, id); calls++;
      const cpf = tkcExtractCpf_(m.data || []);
      if (cpf) found++;
      const total = (m.pagination && m.pagination.total) || (m.data || []).length;
      lote.push("(" + id + "," + tkcLit_(cpf) + "," + (cpf ? "'messages'" : "NULL") + "," + Number(total) + ",NOW())");
      done++;
      if (lote.length >= 50) flushCpf();
    }
    flushCpf();
  } finally { stmt.close(); }
  Logger.log("tkcCpfEnrich: %s tickets verificados, %s com CPF (%s telefones pelo objeto de contato), %s chamadas%s", done, found, viaContato, calls,
    props.getProperty(TKC.PROP_CPF_SINCE) ? " (backfill desde " + props.getProperty(TKC.PROP_CPF_SINCE) + ")" : "");
  return found;
}

/** Primeira mensagem inbound que é só um CPF (11 dígitos, com ou sem pontuação). */
function tkcExtractCpf_(msgs) {
  for (let i = 0; i < msgs.length; i++) {
    const m = msgs[i];
    if (m.direction !== "inbound" || !m.body) continue;
    const compact = String(m.body).replace(/\s/g, "");
    const digits = compact.replace(/\D/g, "");
    if (digits.length === 11 && compact.length <= 14 && !/^(\d)\1{10}$/.test(digits)) return digits;
  }
  return null;
}

/* ------------------------------------------------------------------ */
/*  Fila / utilitários                                                 */
/* ------------------------------------------------------------------ */

function tkcLoadJobs_() {
  const raw = PropertiesService.getScriptProperties().getProperty(TKC.PROP_JOBS);
  return raw ? JSON.parse(raw) : [];
}
function tkcSaveJobs_(jobs) {
  PropertiesService.getScriptProperties().setProperty(TKC.PROP_JOBS, JSON.stringify(jobs));
}
/** Enfileira 1 job por dia (janelas curtas = retomada barata). Não duplica job igual já pendente.
 *  front=true coloca os jobs no início da fila (prioridade sobre o backfill). */
function tkcEnqueueDays_(jobs, field, from, to, front) {
  let d = tkcParseDate_(from);
  const end = tkcParseDate_(to);
  const novos = [];
  while (d <= end) {
    const day = tkcFmtDate_(d);
    const dup = jobs.some(function (j) { return j.field === field && j.start === day && j.end === day; });
    if (!dup) novos.push({ field: field, start: day, end: day, page: 1, totalPages: null });
    d = tkcAddDays_(d, 1);
  }
  if (front) { Array.prototype.unshift.apply(jobs, novos); } else { Array.prototype.push.apply(jobs, novos); }
}
function tkcIsoToLocal_(iso) {
  if (!iso) return null;
  return Utilities.formatDate(new Date(iso), TKC.TZ, "yyyy-MM-dd HH:mm:ss");
}
function tkcFmtDate_(d) { return Utilities.formatDate(d, TKC.TZ, "yyyy-MM-dd"); }
function tkcParseDate_(s) { const p = s.split("-"); return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]), 12); }
function tkcAddDays_(d, n) { const x = new Date(d.getTime()); x.setDate(x.getDate() + n); return x; }

/** Conexão própria (mesmo padrão do Checkout_Funnel.gs) + cria a tabela se não existir. */
function tkcConn_() {
  const props = PropertiesService.getScriptProperties();
  const conn = Jdbc.getConnection(props.getProperty("DB_URL"), props.getProperty("DB_USER"), props.getProperty("DB_PASS"));
  conn.createStatement().execute("SET time_zone = '-03:00'");
  conn.createStatement().execute(
    "CREATE TABLE IF NOT EXISTS " + TKC.TABLE + " (" +
    " id BIGINT NOT NULL PRIMARY KEY," +
    " status VARCHAR(20) NULL, channel VARCHAR(20) NULL, attended_by_bot TINYINT(1) NULL," +
    " contact_id BIGINT NULL, contact_name VARCHAR(255) NULL, telefone VARCHAR(32) NULL, telefone_key VARCHAR(8) NULL," +
    " queue_id INT NULL, queue VARCHAR(100) NULL, agent_id INT NULL, agent VARCHAR(255) NULL, agent_email VARCHAR(255) NULL," +
    " close_reason_id INT NULL, close_reason VARCHAR(255) NULL," +
    " created_at DATETIME NULL, opened_at DATETIME NULL, closed_at DATETIME NULL, updated_at DATETIME NULL," +
    " cpf VARCHAR(11) NULL, cpf_source VARCHAR(16) NULL, msgs_total INT NULL, msgs_checked_at DATETIME NULL," +
    " loaded_at DATETIME NULL," +
    " KEY ix_created (created_at), KEY ix_closed (closed_at), KEY ix_tel8 (telefone_key), KEY ix_cpf (cpf), KEY ix_reason (close_reason_id)" +
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci");
  return conn;
}
