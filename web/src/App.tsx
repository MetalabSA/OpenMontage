import { useCallback, useEffect, useRef, useState } from "react";
import { api, clearToken, fetchBlob, getToken, setToken, verifyToken } from "./api";

const STATUS_LABEL: Record<string, string> = {
  draft: "BORRADOR",
  in_progress: "EN CURSO",
  awaiting_human: "ESPERANDO APROBACIÓN",
  composing: "COMPONIENDO",
  ready: "LISTO",
  failed: "FALLÓ",
  archived: "ARCHIVADO",
  pending: "PENDIENTE",
  running: "CORRIENDO",
  queued: "EN COLA",
  succeeded: "COMPLETADO",
  completed: "COMPLETADO",
  cancelled: "CANCELADO",
  approved: "APROBADO",
  rejected: "RECHAZADO",
  not_required: "PRÓXIMO",
};

const PLATFORMS = [
  ["instagram_reels", "Instagram Reels · 9:16"],
  ["tiktok", "TikTok · 9:16"],
  ["youtube_shorts", "YouTube Shorts · 9:16"],
  ["youtube_landscape", "YouTube · 16:9"],
  ["linkedin", "LinkedIn · 16:9"],
];

function Pill({ status }: { status: string }) {
  return <span className={`pill ${status}`}>{STATUS_LABEL[status] || status}</span>;
}

function useMedia(path?: string | null) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!path) {
      setSrc(null);
      return;
    }
    let objectUrl: string | null = null;
    const controller = new AbortController();
    (async () => {
      try {
        objectUrl = await fetchBlob(path);
        if (!controller.signal.aborted) setSrc(objectUrl);
      } catch {
        setSrc(null);
      }
    })();
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);
  return src;
}

function MediaImage({ path, alt = "" }: { path?: string | null; alt?: string }) {
  const src = useMedia(path);
  if (!src) return <div className="media-placeholder" />;
  if (path && /\.(mp4|webm|mov)$/i.test(path.split("?")[0])) {
    return <video className="media" src={src} muted playsInline preload="metadata" />;
  }
  return <img className="media" src={src} alt={alt} />;
}

function MediaVideo({ path }: { path: string }) {
  const src = useMedia(path);
  if (!src) return <div className="media-placeholder" />;
  return <video className="media-video" src={src} controls playsInline />;
}

function useLive(slug: string, onEvent: () => void) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    (async () => {
      try {
        const response = await fetch(`/api/events?project=${encodeURIComponent(slug)}`, {
          headers: { Authorization: `Bearer ${getToken()}` },
          signal: controller.signal,
        });
        if (!response.body) return;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (active) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() || "";
          for (const chunk of chunks) {
            if (chunk.includes("event:")) handler.current();
          }
        }
      } catch {
        /* stream closed or network error: polling remains as fallback */
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [slug]);
}

function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    const ok = await verifyToken(value.trim());
    setBusy(false);
    if (ok) {
      setToken(value);
      onLogin(value.trim());
    } else {
      setError("El token no es válido o venció.");
    }
  };
  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="kicker">OPENMONTAGE · CABINA STUDIO</div>
        <h1>Entrar al estudio</h1>
        <p className="muted">Pegá el API token de la instancia. Queda guardado solo en este navegador.</p>
        <input
          className="input"
          type="password"
          placeholder="om_..."
          value={value}
          onChange={(event) => setValue(event.target.value)}
          autoFocus
        />
        {error && <div className="error-text">{error}</div>}
        <button className="btn primary" disabled={busy || value.trim().length < 10}>
          {busy ? "Verificando…" : "Entrar"}
        </button>
        <p className="hint">El token está en `.secrets/studio-api.txt` del servidor.</p>
      </form>
    </div>
  );
}

function Library({ onOpen, onLogout }: { onOpen: (slug: string) => void; onLogout: () => void }) {
  const [projects, setProjects] = useState<any[]>([]);
  const [pipelines, setPipelines] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [title, setTitle] = useState("");
  const [pipeline, setPipeline] = useState("animated-explainer");
  const [platform, setPlatform] = useState("instagram_reels");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [list, catalog] = await Promise.all([api.get("/projects"), api.get("/pipelines")]);
      setProjects(list.data || []);
      setPipelines(catalog.pipelines || []);
      if (!pipeline && catalog.pipelines?.length) setPipeline(catalog.pipelines[0].name);
    } catch (err: any) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const project = await api.post("/projects", { title, pipeline, platform });
      setShowNew(false);
      setTitle("");
      onOpen(project.slug);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <span className="clapper" />
          <span className="wordmark">CABINA STUDIO</span>
        </div>
        <div className="topbar-actions">
          <button className="btn primary" onClick={() => setShowNew(true)}>Nueva producción</button>
          <button className="btn ghost" onClick={onLogout}>Salir</button>
        </div>
      </header>
      <main className="library">
        <div className="section-head">
          <div>
            <div className="kicker">BIBLIOTECA</div>
            <h1>Producciones</h1>
          </div>
          <div className="muted">{projects.length} proyectos</div>
        </div>
        {error && <div className="error-banner">{error}</div>}
        <div className="grid">
          {projects.map((project) => (
            <button key={project.slug} className="project-card" onClick={() => onOpen(project.slug)}>
              <div className="poster">
                {project.poster_url ? <MediaImage path={project.poster_url} alt={project.title} /> : <div className="poster-empty">SIN RENDER</div>}
              </div>
              <div className="project-body">
                <div className="project-top">
                  <span className="mono">PROD. NO. {String(project.prod_no || 0).padStart(4, "0")}</span>
                  <Pill status={project.status} />
                </div>
                <h3>{project.title}</h3>
                <div className="meta">
                  <span>{project.pipeline}</span>
                  <span>{project.duration_seconds ? `${project.duration_seconds}s` : "—"}</span>
                  <span>${Number(project.cost_usd || 0).toFixed(3)}</span>
                </div>
              </div>
            </button>
          ))}
          {!projects.length && (
            <div className="empty-card">
              <div className="kicker">SIN PRODUCCIONES</div>
              <p>Creá la primera y el agente se encarga del research, guion y storyboard.</p>
            </div>
          )}
        </div>
      </main>
      {showNew && (
        <div className="modal-backdrop" onClick={() => setShowNew(false)}>
          <form className="modal" onClick={(event) => event.stopPropagation()} onSubmit={create}>
            <div className="kicker">NUEVA PRODUCCIÓN</div>
            <h2>¿Qué vamos a filmar?</h2>
            <label className="field">
              <span>Título</span>
              <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} required autoFocus />
            </label>
            <label className="field">
              <span>Pipeline</span>
              <select className="input" value={pipeline} onChange={(event) => setPipeline(event.target.value)}>
                {pipelines.map((item) => (
                  <option key={item.name} value={item.name}>{item.name} · {item.stability}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Plataforma</span>
              <select className="input" value={platform} onChange={(event) => setPlatform(event.target.value)}>
                {PLATFORMS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            {error && <div className="error-text">{error}</div>}
            <div className="modal-actions">
              <button type="button" className="btn ghost" onClick={() => setShowNew(false)}>Cancelar</button>
              <button className="btn primary" disabled={busy || title.trim().length < 3}>{busy ? "Creando…" : "Crear y abrir"}</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

function StageRail({ stages }: { stages: any[] }) {
  return (
    <div className="stage-rail">
      {stages.map((stage, index) => (
        <div key={stage.name} className={`stage ${stage.status}`}>
          <div className="stage-dot">{stage.status === "completed" ? "✓" : index + 1}</div>
          <div className="stage-label">
            <span>{stage.name}</span>
            {stage.gate && <span className="gate-mini">gate</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function GateBar({ gate, onApprove, onReject }: { gate: any; onApprove: (note: string) => Promise<void>; onReject: (note: string) => Promise<void> }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (fn: (note: string) => Promise<void>) => {
    setBusy(true);
    try {
      await fn(note);
      setNote("");
    } catch (err: any) {
      alert(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="gate-bar">
      <div>
        <div className="kicker">GATE PENDIENTE</div>
        <strong>{gate.stage}</strong> espera tu aprobación antes de avanzar.
      </div>
      <input className="input gate-note" placeholder="Nota (opcional para aprobar, obligatoria para rechazar)" value={note} onChange={(event) => setNote(event.target.value)} />
      <button className="btn primary" disabled={busy} onClick={() => run(onApprove)}>Aprobar</button>
      <button className="btn danger" disabled={busy || !note.trim()} onClick={() => run(onReject)}>Rechazar</button>
    </div>
  );
}

function Storyboard({ slug, scenes, onRefresh }: { slug: string; scenes: any[]; onRefresh: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const regenerate = async (scene: any) => {
    setBusy(scene.id);
    try {
      await api.post(`/projects/${slug}/scenes/${scene.id}/regenerate`, { instructions: `Regenerar ${scene.id} manteniendo el estilo aprobado.` });
      onRefresh();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setBusy(null);
    }
  };
  if (!scenes.length) {
    return (
      <div className="empty-card">
        <div className="kicker">SIN ESCENAS TODAVÍA</div>
        <p>Cuando el pipeline llegue a <code>scene_plan</code>, el storyboard aparece acá con sus tarjetas, costos y scores.</p>
      </div>
    );
  }
  return (
    <div className="storyboard">
      {scenes.map((scene) => (
        <article key={scene.id} className={`scene-card ${scene.hero ? "hero" : ""}`}>
          <div className="scene-head">
            <span className="mono">SC {String(scene.index).padStart(2, "0")}</span>
            <span className="mono">{Number(scene.end_seconds - scene.start_seconds).toFixed(1)}s</span>
            {scene.hero && <span className="badge hero-badge">HERO</span>}
            <Pill status={scene.status} />
          </div>
          <div className="scene-media">
            {scene.thumbnail_url ? <MediaImage path={scene.thumbnail_url} /> : <div className="poster-empty">SIN ASSET</div>}
          </div>
          <p className="scene-desc">{scene.description || scene.title || "Escena sin descripción"}</p>
          <div className="chips">
            {(scene.tags || []).map((tag: string) => <span key={tag} className="chip">{tag}</span>)}
          </div>
          <div className="scene-foot">
            <span className="mono">{scene.provider || "—"} · q {scene.quality_score ?? "—"} · ${Number(scene.cost_usd || 0).toFixed(2)}</span>
            <button className="btn tiny" disabled={busy === scene.id} onClick={() => regenerate(scene)}>
              {busy === scene.id ? "…" : "Regenerar"}
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

function ChatRail({ slug, messages, onRefresh, decisions, cost }: { slug: string; messages: any[]; onRefresh: () => void; decisions: any[]; cost: any }) {
  const [text, setText] = useState("");
  const [model, setModel] = useState("deepseek-flash");
  const [busy, setBusy] = useState(false);
  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    try {
      await api.post(`/projects/${slug}/chat`, { content: text.trim(), model });
      setText("");
      setTimeout(onRefresh, 600);
    } catch (err: any) {
      alert(err.message);
    } finally {
      setBusy(false);
    }
  };
  const runAction = async (action: any) => {
    try {
      if (action.type === "undo") await api.post(`/projects/${slug}/undo`, {});
      else if (action.type === "retry" && action.payload?.job_id) await api.post(`/jobs/${action.payload.job_id}/cancel`, {});
      else if (action.type === "approve") await api.post(`/projects/${slug}/gates/${action.payload?.stage}/approve`, {});
      else if (action.type === "open_scene") return;
      onRefresh();
    } catch (err: any) {
      alert(err.message);
    }
  };
  const spent = Number(cost?.spent_usd || 0);
  const budget = Number(cost?.budget_usd || 0);
  return (
    <aside className="rail">
      <div className="rail-head">
        <div className="kicker">CHAT DE PRODUCCIÓN</div>
        <span className="live"><i /> AGENTE</span>
      </div>
      <div className="messages">
        {messages.map((message) => (
          <div key={message.id} className={`message ${message.role}`}>
            <div className="message-body">{message.content}</div>
            <div className="message-meta mono">{message.model || message.role}</div>
            {!!message.actions?.length && (
              <div className="message-actions">
                {message.actions.map((action: any) => (
                  <button key={action.id} className="btn tiny" onClick={() => runAction(action)}>{action.label}</button>
                ))}
              </div>
            )}
          </div>
        ))}
        {!messages.length && <p className="muted small">Pedile algo al agente: “hacé el guion”, “regenerá la escena 2”, “aprobá la propuesta”.</p>}
      </div>
      <form className="composer" onSubmit={send}>
        <textarea className="input" rows={2} placeholder="Dirige al agente…" value={text} onChange={(event) => setText(event.target.value)} />
        <div className="composer-row">
          <select className="input select" value={model} onChange={(event) => setModel(event.target.value)}>
            <option value="deepseek-flash">DEEPSEEK · FLASH</option>
            <option value="deepseek-v4-pro">DEEPSEEK · PRO</option>
            <option value="claude-sonnet-5.5">CLAUDE · SONNET</option>
          </select>
          <button className="btn send" disabled={busy || !text.trim()}>{busy ? "…" : "Enviar"}</button>
        </div>
      </form>
      <div className="rail-block">
        <div className="rail-title"><span className="kicker">REGISTRO DE DECISIONES</span><span className="mono">{String(decisions.length).padStart(2, "0")}</span></div>
        {decisions.slice(-4).map((decision) => (
          <div key={decision.id} className="decision">
            <div className="mono category">{decision.category}</div>
            <div>{decision.subject}</div>
            <div className="muted small">{decision.chosen}</div>
          </div>
        ))}
        {!decisions.length && <p className="muted small">Sin decisiones registradas todavía.</p>}
      </div>
      <div className="rail-block cost">
        <div className="rail-title"><span className="kicker">GASTO</span><span className="mono">${spent.toFixed(3)} / ${budget.toFixed(2)}</span></div>
        <div className="cost-bar"><span style={{ width: `${Math.min(100, budget ? (spent / budget) * 100 : 0)}%` }} /></div>
      </div>
    </aside>
  );
}

function Workspace({ slug, onBack, onLogout }: { slug: string; onBack: () => void; onLogout: () => void }) {
  const [project, setProject] = useState<any>(null);
  const [board, setBoard] = useState<any>(null);
  const [chat, setChat] = useState<any[]>([]);
  const [brief, setBrief] = useState<any>(null);
  const [script, setScript] = useState<any>(null);
  const [tab, setTab] = useState("storyboard");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [projectData, boardData, chatData] = await Promise.all([
        api.get(`/projects/${slug}`),
        api.get(`/projects/${slug}/board`),
        api.get(`/projects/${slug}/chat`),
      ]);
      setProject(projectData);
      setBoard(boardData);
      setChat(chatData.data || []);
      setBrief(await api.get(`/projects/${slug}/artifacts/brief`).catch(() => null));
      setScript(await api.get(`/projects/${slug}/artifacts/script`).catch(() => null));
      setError("");
    } catch (err: any) {
      setError(err.message);
    }
  }, [slug]);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(refresh, 10000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  const timer = useRef<number | null>(null);
  useLive(slug, () => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void refresh(), 500);
  });

  if (error && !project) {
    return (
      <div className="page">
        <header className="topbar"><button className="btn ghost" onClick={onBack}>← Biblioteca</button></header>
        <div className="error-banner">{error}</div>
      </div>
    );
  }
  if (!project || !board) {
    return <div className="page loading">Cargando producción…</div>;
  }

  const pendingGate = (board.gates || []).find((gate: any) => gate.status === "pending");
  const approve = async (note: string) => {
    await api.post(`/projects/${slug}/gates/${pendingGate.stage}/approve`, { note });
    await refresh();
  };
  const reject = async (note: string) => {
    await api.post(`/projects/${slug}/gates/${pendingGate.stage}/reject`, { note });
    await refresh();
  };

  return (
    <div className="page workspace-page">
      <header className="topbar">
        <div className="topbar-left">
          <button className="btn ghost" onClick={onBack}>←</button>
          <div>
            <div className="mono breadcrumb">PROD. NO. {String(project.prod_no || 0).padStart(4, "0")} · {project.version}</div>
            <strong className="title">{project.title}</strong>
          </div>
        </div>
        <div className="topbar-actions">
          <Pill status={project.status} />
          <span className="mono">${Number(project.cost_usd || 0).toFixed(3)}</span>
          <button className="btn ghost" onClick={onLogout}>Salir</button>
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <div className="kicker">PIPELINE</div>
          <div className="pipeline-name">{project.pipeline}</div>
          <div className="sidebar-section">
            <div className="kicker">ARTEFACTOS</div>
            {(board.artifacts || []).map((artifact: any) => (
              <div key={artifact.name} className="asset-row">
                <span>{artifact.name}</span>
                <span className={`dot-status ${artifact.valid ? "ok" : "bad"}`} />
              </div>
            ))}
          </div>
          <div className="sidebar-section">
            <div className="kicker">RENDERS</div>
            {(board.renders || []).map((render: any) => (
              <div key={render.id} className="asset-row"><span>{render.path}</span></div>
            ))}
            {!board.renders?.length && <p className="muted small">Sin renders.</p>}
          </div>
        </aside>
        <main className="board">
          <StageRail stages={board.stages || []} />
          {pendingGate && <GateBar gate={pendingGate} onApprove={approve} onReject={reject} />}
          <div className="tabs">
            {[["brief", "Brief"], ["script", "Guion"], ["storyboard", "Storyboard"], ["renders", "Renders"]].map(([key, label]) => (
              <button key={key} className={`tab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>{label}</button>
            ))}
          </div>
          <div className="tab-body">
            {tab === "brief" && (
              <div className="brief">
                {brief?.data ? (
                  <>
                    <div className="kicker">BRIEF</div>
                    <h2>{brief.data.title}</h2>
                    <p className="hook">{brief.data.hook}</p>
                    <div className="kv">
                      <div><span>Tono</span><strong>{brief.data.tone}</strong></div>
                      <div><span>Estilo</span><strong>{brief.data.style}</strong></div>
                      <div><span>Plataforma</span><strong>{brief.data.target_platform}</strong></div>
                      <div><span>Duración</span><strong>{brief.data.target_duration_seconds}s</strong></div>
                    </div>
                    <ul className="points">{(brief.data.key_points || []).map((point: string) => <li key={point}>{point}</li>)}</ul>
                  </>
                ) : <div className="empty-card"><div className="kicker">SIN BRIEF</div><p>El brief se crea al inicializar la producción.</p></div>}
              </div>
            )}
            {tab === "script" && (
              <div className="script">
                {script?.data ? (
                  <>
                    <div className="kicker">GUION · {script.data.total_duration_seconds}s</div>
                    <h2>{script.data.title}</h2>
                    {(script.data.sections || []).map((section: any, index: number) => (
                      <div key={section.id || index} className="script-section">
                        <div className="mono">{section.label || `S${index + 1}`} · {section.start_seconds}s → {section.end_seconds}s</div>
                        <p>{section.text}</p>
                      </div>
                    ))}
                  </>
                ) : <div className="empty-card"><div className="kicker">SIN GUION</div><p>Aprobá la propuesta para que el agente escriba el guion.</p></div>}
              </div>
            )}
            {tab === "storyboard" && <Storyboard slug={slug} scenes={board.scenes || []} onRefresh={refresh} />}
            {tab === "renders" && (
              <div className="renders">
                {(board.renders || []).map((render: any) => (
                  <div key={render.id} className="render-card">
                    <div className="mono">{render.path}</div>
                    <MediaVideo path={render.url} />
                  </div>
                ))}
                {!board.renders?.length && <div className="empty-card"><div className="kicker">SIN RENDERS</div><p>Cuando se aprueben todos los gates, el compose genera el MP4.</p></div>}
              </div>
            )}
          </div>
        </main>
        <ChatRail slug={slug} messages={chat} onRefresh={refresh} decisions={board.decisions || []} cost={board.cost} />
      </div>
    </div>
  );
}

export default function App() {
  const [token, setTok] = useState(getToken());
  const [route, setRoute] = useState(window.location.hash || "#/");
  useEffect(() => {
    const onHash = () => setRoute(window.location.hash || "#/");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const logout = () => {
    clearToken();
    setTok("");
    window.location.hash = "#/";
  };
  if (!token) return <Login onLogin={setTok} />;
  const slug = route.startsWith("#/p/") ? route.slice(4) : "";
  if (slug) return <Workspace key={slug} slug={slug} onBack={() => (window.location.hash = "#/")} onLogout={logout} />;
  return <Library onOpen={(next) => (window.location.hash = `#/p/${next}`)} onLogout={logout} />;
}
