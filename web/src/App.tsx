import { useCallback, useEffect, useRef, useState } from "react";
import { api, clearToken, fetchBlob, fetchMe, getToken, getUser, loginWithPassword, logoutSession, setToken, verifyToken } from "./api";

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

function Login({ onLogin, onSession }: { onLogin: (token: string) => void; onSession: (user: any) => void }) {
  const [mode, setMode] = useState<"account" | "token">("account");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tokenValue, setTokenValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submitAccount = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await loginWithPassword(email.trim(), password);
      onSession(user);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const submitToken = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    const ok = await verifyToken(tokenValue.trim());
    setBusy(false);
    if (ok) {
      setToken(tokenValue);
      onLogin(tokenValue.trim());
    } else {
      setError("El token no es válido o venció.");
    }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="kicker">OPENMONTAGE · CABINA STUDIO</div>
        <h1>Entrar al estudio</h1>
        <div className="auth-tabs" role="tablist" aria-label="Método de acceso">
          <button role="tab" aria-selected={mode === "account"} className={`tab ${mode === "account" ? "active" : ""}`} onClick={() => setMode("account")}>Cuenta</button>
          <button role="tab" aria-selected={mode === "token"} className={`tab ${mode === "token" ? "active" : ""}`} onClick={() => setMode("token")}>API token</button>
        </div>
        {mode === "account" ? (
          <form className="login-form" onSubmit={submitAccount}>
            <p className="muted">Ingresá con tu usuario y contraseña.</p>
            <input className="input" type="email" placeholder="email@metalabia.com" value={email} onChange={(event) => setEmail(event.target.value)} autoFocus required />
            <input className="input" type="password" placeholder="Contraseña" value={password} onChange={(event) => setPassword(event.target.value)} required />
            {error && <div className="error-text">{error}</div>}
            <button className="btn primary" disabled={busy || !email || !password}>{busy ? "Entrando…" : "Entrar"}</button>
          </form>
        ) : (
          <form className="login-form" onSubmit={submitToken}>
            <p className="muted">Pegá el API token de la instancia. Queda guardado solo en este navegador.</p>
            <input className="input" type="password" placeholder="om_..." value={tokenValue} onChange={(event) => setTokenValue(event.target.value)} autoFocus />
            {error && <div className="error-text">{error}</div>}
            <button className="btn primary" disabled={busy || tokenValue.trim().length < 10}>{busy ? "Verificando…" : "Entrar"}</button>
            <p className="hint">El token está en `.secrets/studio-api.txt` del servidor.</p>
          </form>
        )}
      </div>
    </div>
  );
}

function Library({ onOpen, onLogout, user }: { onOpen: (slug: string) => void; onLogout: () => void; user: any }) {
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
          <button className="btn ghost" onClick={() => (window.location.hash = "#/jobs")}>Jobs</button>
          <button className="btn ghost" onClick={() => (window.location.hash = "#/providers")}>Providers</button>
          <button className="btn ghost" onClick={() => (window.location.hash = "#/settings")}>Settings</button>
          {user?.role === "admin" && <button className="btn ghost" onClick={() => (window.location.hash = "#/ops")}>Ops</button>}
          {user?.role === "admin" && <button className="btn ghost" onClick={() => (window.location.hash = "#/users")}>Usuarios</button>}
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

function Storyboard({ slug, scenes, onRefresh, onOpen }: { slug: string; scenes: any[]; onRefresh: () => void; onOpen: (scene: any) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);

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

  const drop = async (target: string) => {
    const source = dragId;
    setDragId(null);
    setOverId(null);
    if (!source || source === target) return;
    const ids = scenes.map((scene) => scene.id);
    const from = ids.indexOf(source);
    const to = ids.indexOf(target);
    if (from < 0 || to < 0) return;
    ids.splice(to, 0, ids.splice(from, 1)[0]);
    try {
      await api.put(`/projects/${slug}/scenes/order`, { order: ids });
      onRefresh();
    } catch (err: any) {
      alert(err.message);
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
    <div>
      <p className="hint">Arrastrá las tarjetas para reordenar · Enter abre el editor · ← → navega.</p>
      <div className="storyboard">
        {scenes.map((scene) => (
          <article
            key={scene.id}
            id={`scene-${scene.id}`}
            tabIndex={0}
            draggable
            onDragStart={() => setDragId(scene.id)}
            onDragOver={(event) => { event.preventDefault(); setOverId(scene.id); }}
            onDragLeave={() => setOverId((current) => (current === scene.id ? null : current))}
            onDrop={(event) => { event.preventDefault(); event.stopPropagation(); void drop(scene.id); }}
            onClick={() => onOpen(scene)}
            onKeyDown={(event) => { if (event.key === "Enter") onOpen(scene); }}
            aria-label={`Escena ${scene.index}: ${scene.description || scene.title || ""}`}
            className={`scene-card ${scene.hero ? "hero" : ""} ${overId === scene.id ? "drop" : ""}`}
          >
            <div className="scene-head">
              <span className="drag" aria-hidden="true">⠿</span>
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
              <button className="btn tiny" disabled={busy === scene.id} onClick={(event) => { event.stopPropagation(); void regenerate(scene); }}>
                {busy === scene.id ? "…" : "Regenerar"}
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function SceneDrawer({ scene, onClose, onRegenerate }: { scene: any; onClose: () => void; onRegenerate: (scene: any, instructions: string) => Promise<void> }) {
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const regenerate = async () => {
    setBusy(true);
    try {
      await onRegenerate(scene, instructions);
      onClose();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal drawer" role="dialog" aria-modal="true" aria-label={`Editar escena ${scene.index}`} onClick={(event) => event.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <div className="kicker">ESCENA {String(scene.index).padStart(2, "0")}</div>
            <h2>{scene.title || scene.description || "Escena"}</h2>
          </div>
          <button className="btn ghost" onClick={onClose} aria-label="Cerrar">✕</button>
        </div>
        <div className="drawer-preview"><MediaImage path={scene.thumbnail_url} /></div>
        <dl className="kv">
          <div><span>Duración</span><strong>{Number(scene.end_seconds - scene.start_seconds).toFixed(1)}s</strong></div>
          <div><span>Proveedor</span><strong>{scene.provider || "—"}</strong></div>
          <div><span>Modelo</span><strong>{scene.model || "—"}</strong></div>
          <div><span>Score</span><strong>{scene.quality_score ?? "—"}</strong></div>
          <div><span>Costo</span><strong>${Number(scene.cost_usd || 0).toFixed(2)}</strong></div>
          <div><span>Estado</span><strong>{scene.status}</strong></div>
        </dl>
        <p className="muted">{scene.description}</p>
        <label className="field">
          <span>Instrucciones para regenerar</span>
          <textarea className="input" rows={3} value={instructions} onChange={(event) => setInstructions(event.target.value)} placeholder="Ej: más dramático, plano cerrado, luz cálida…" />
        </label>
        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cerrar</button>
          <button className="btn primary" disabled={busy} onClick={regenerate}>{busy ? "Encolando…" : "Regenerar escena"}</button>
        </div>
      </div>
    </div>
  );
}

function Timeline({ scenes, assets, script }: { scenes: any[]; assets: any[]; script: any }) {
  const total = Math.max(1, ...scenes.map((scene) => Number(scene.end_seconds) || 0));
  const audio = assets.filter((asset) => ["audio", "music", "narration"].includes(asset.type));
  const sections = script?.data?.sections || [];
  const width = (start: number, end: number) => `${Math.max(0.5, ((end - start) / total) * 100)}%`;
  const left = (start: number) => `${(start / total) * 100}%`;
  return (
    <div className="timeline">
      <div className="track">
        <span className="track-label">VIDEO</span>
        <div className="lane">
          {scenes.map((scene) => (
            <div key={scene.id} className="clip video" style={{ left: left(scene.start_seconds), width: width(scene.start_seconds, scene.end_seconds) }} title={scene.description}>
              SC {String(scene.index).padStart(2, "0")}
            </div>
          ))}
          {!scenes.length && <span className="muted small">Sin escenas</span>}
        </div>
      </div>
      <div className="track">
        <span className="track-label">AUDIO</span>
        <div className="lane">
          {audio.map((asset) => (
            <div key={asset.id} className="clip audio" style={{ left: "0%", width: width(0, Math.min(total, asset.duration_seconds || total)) }} title={asset.path}>
              {asset.type}
            </div>
          ))}
          {!audio.length && <span className="muted small">Sin audio todavía</span>}
        </div>
      </div>
      <div className="track">
        <span className="track-label">CAPTIONS</span>
        <div className="lane">
          {sections.map((section: any, index: number) => (
            <div key={section.id || index} className="clip caption" style={{ left: left(section.start_seconds || 0), width: width(section.start_seconds || 0, section.end_seconds || total) }}>
              {(section.text || "").slice(0, 40)}
            </div>
          ))}
          {!sections.length && <span className="muted small">Sin guion</span>}
        </div>
      </div>
    </div>
  );
}

function ScreenShell({ title, onBack, children }: { title: string; onBack: () => void; children: React.ReactNode }) {
  return (
    <div className="page">
      <header className="topbar">
        <div className="topbar-left">
          <button className="btn ghost" onClick={onBack} aria-label="Volver">←</button>
          <strong className="title">{title}</strong>
        </div>
      </header>
      <main className="screen">{children}</main>
    </div>
  );
}

function JobsScreen({ onBack, onOpenProject }: { onBack: () => void; onOpenProject: (slug: string) => void }) {
  const [jobs, setJobs] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [log, setLog] = useState<any>(null);
  const load = useCallback(async () => {
    try {
      const payload = await api.get("/jobs?limit=50");
      setJobs(payload.data || []);
    } catch (err: any) {
      setError(err.message);
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, [load]);
  const openLog = async (job: any) => {
    try {
      const payload = await api.get(`/jobs/${job.id}/log`);
      setLog(payload);
    } catch (err: any) {
      setError(err.message);
    }
  };
  return (
    <ScreenShell title="Jobs" onBack={onBack}>
      {error && <div className="error-banner">{error}</div>}
      <div className="table">
        <div className="tr head"><span>Job</span><span>Proyecto</span><span>Stage</span><span>Modelo</span><span>Estado</span><span>Costo</span><span /></div>
        {jobs.map((job) => (
          <div key={job.id} className="tr">
            <span className="mono">{job.id.slice(0, 12)}</span>
            <button className="link" onClick={() => onOpenProject(job.project_id)}>{job.project_id}</button>
            <span>{job.stage || "—"}</span>
            <span className="mono">{job.model || "—"}</span>
            <span><Pill status={job.status} /> <span className="muted small">{job.progress?.percent ?? 0}%</span></span>
            <span className="mono">${Number(job.cost_usd || 0).toFixed(4)}</span>
            <button className="btn tiny" onClick={() => openLog(job)}>Log</button>
            {job.error && <span className="error-text tr-error">{job.error}</span>}
          </div>
        ))}
        {!jobs.length && <div className="empty-card">Sin jobs todavía.</div>}
      </div>
      {log && (
        <div className="log-panel">
          <div className="rail-title"><span className="kicker">LOG {log.data?.[0] ? "" : ""}</span><button className="btn tiny" onClick={() => setLog(null)}>Cerrar</button></div>
          <pre>{log.data.map((item: any) => `${item.created_at} ${item.type} ${JSON.stringify(item.payload)}`).join("\n") || "Sin eventos"}</pre>
        </div>
      )}
    </ScreenShell>
  );
}

function ProvidersScreen({ onBack }: { onBack: () => void }) {
  const [menu, setMenu] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get("/providers").then(setMenu).catch((err) => setError(err.message));
  }, []);
  return (
    <ScreenShell title="Providers" onBack={onBack}>
      {error && <div className="error-banner">{error}</div>}
      {menu && (
        <>
          <div className="runtime-row">
            {Object.entries(menu.composition_runtimes || {}).map(([name, ok]) => (
              <div key={name} className={`runtime ${ok ? "ok" : "bad"}`}><span className="dot-status" /> {name} <span className="mono">{ok ? "ON" : "OFF"}</span></div>
            ))}
          </div>
          <div className="capabilities">
            {(menu.capabilities || []).map((cap: any) => (
              <div key={cap.capability} className="capability">
                <div className="cap-head"><span>{cap.capability}</span><span className="mono">{cap.configured}/{cap.total}</span></div>
                <div className="cost-bar"><span style={{ width: `${cap.total ? (cap.configured / cap.total) * 100 : 0}%` }} /></div>
                <div className="muted small">{cap.available_providers?.join(" · ") || "sin proveedores configurados"}</div>
              </div>
            ))}
          </div>
          {(menu.runtime_warnings || []).map((warning: string) => <div key={warning} className="hint">⚠ {warning}</div>)}
        </>
      )}
    </ScreenShell>
  );
}

const STAGE_KEYS = ["research", "proposal", "script", "scene_plan", "assets", "edit", "compose", "publish"];
const MODEL_OPTIONS = ["deepseek-flash", "deepseek-v4-pro", "claude-sonnet-5.5"];

function SettingsScreen({ onBack }: { onBack: () => void }) {
  const [settings, setSettings] = useState<any>(null);
  const [map, setMap] = useState<Record<string, string>>({});
  const [budget, setBudget] = useState(2);
  const [projectsDays, setProjectsDays] = useState(90);
  const [rendersDays, setRendersDays] = useState(30);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [storage, setStorage] = useState<any>(null);
  const [backupList, setBackupList] = useState<any[]>([]);
  const [backupBusy, setBackupBusy] = useState(false);
  const [verifyReport, setVerifyReport] = useState<any>(null);
  const [retentionReport, setRetentionReport] = useState<any>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    api.get("/settings").then((payload) => {
      setSettings(payload);
      setMap(payload.engine?.default_map || {});
      setBudget(Number(payload.budget?.total_usd ?? 2));
      setProjectsDays(Number(payload.retention?.projects_days ?? 90));
      setRendersDays(Number(payload.retention?.renders_days ?? 30));
    }).catch((err) => setError(err.message));
    void loadOps();
  }, []);

  const loadOps = async () => {
    try {
      const [storageData, backupData] = await Promise.all([api.get("/admin/storage"), api.get("/admin/backups")]);
      setStorage(storageData);
      setBackupList(backupData.data || []);
    } catch {
      /* admin-only; keep settings usable */
    }
  };

  const createBackup = async () => {
    setBackupBusy(true);
    setStatus("");
    try {
      const createdBackup = await api.post("/admin/backups", {});
      setStatus(`Backup creado: ${createdBackup.name} (${(createdBackup.size / 1024 / 1024).toFixed(1)} MB)`);
      await loadOps();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBackupBusy(false);
    }
  };

  const verifyBackup = async (name: string) => {
    setBackupBusy(true);
    try {
      setVerifyReport(await api.post(`/admin/backups/${name}/verify`, {}));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBackupBusy(false);
    }
  };

  const downloadBackup = async (name: string) => {
    try {
      const url = await fetchBlob(`/api/admin/backups/${name}`);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = name;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const previewRetention = async () => {
    try {
      setRetentionReport(await api.post("/admin/retention", { dry_run: true }));
    } catch (err: any) {
      setError(err.message);
    }
  };
  const save = async () => {
    setError("");
    setStatus("");
    try {
      const providers = Object.fromEntries(Object.entries(keys).filter(([, value]) => value.trim()));
      const payload = await api.put("/settings", {
        engine: { default_map: map },
        budget: { total_usd: Number(budget), mode: "warn" },
        retention: { projects_days: Number(projectsDays), renders_days: Number(rendersDays) },
        backup: settings.backup || { enabled: true, hour: 3, keep: 7 },
        providers,
      });
      setSettings(payload);
      setKeys({});
      setStatus("Guardado.");
    } catch (err: any) {
      setError(err.message);
    }
  };
  return (
    <ScreenShell title="Settings" onBack={onBack}>
      {error && <div className="error-banner">{error}</div>}
      {status && <div className="ok-banner">{status}</div>}
      {!settings ? <p className="muted">Cargando…</p> : (
        <div className="settings-grid">
          <section className="settings-card">
            <div className="kicker">MAPA DE MODELOS POR STAGE</div>
            {STAGE_KEYS.map((stage) => (
              <label key={stage} className="field inline">
                <span>{stage}</span>
                <select className="input" value={map[stage] || "deepseek-flash"} onChange={(event) => setMap({ ...map, [stage]: event.target.value })}>
                  {MODEL_OPTIONS.map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              </label>
            ))}
          </section>
          <section className="settings-card">
            <div className="kicker">PRESUPUESTO Y RETENCIÓN</div>
            <label className="field"><span>Presupuesto por producción (USD)</span><input className="input" type="number" step="0.5" value={budget} onChange={(event) => setBudget(Number(event.target.value))} /></label>
            <label className="field"><span>Retención de proyectos (días)</span><input className="input" type="number" value={projectsDays} onChange={(event) => setProjectsDays(Number(event.target.value))} /></label>
            <label className="field"><span>Retención de renders (días)</span><input className="input" type="number" value={rendersDays} onChange={(event) => setRendersDays(Number(event.target.value))} /></label>
          </section>
          <section className="settings-card wide">
            <div className="kicker">CLAVES DE PROVEEDORES (SOLO ESCRITURA)</div>
            {(settings.providers || []).map((provider: any) => (
              <label key={provider.id} className="field inline">
                <span>{provider.id} <span className="muted small">{provider.configured ? provider.key_preview : "sin configurar"}</span></span>
                <input className="input" type="password" placeholder="nueva clave…" value={keys[provider.id] || ""} onChange={(event) => setKeys({ ...keys, [provider.id]: event.target.value })} />
              </label>
            ))}
          </section>
          <section className="settings-card wide">
            <div className="kicker">BACKUPS Y ALMACENAMIENTO</div>
            {storage && (
              <div className="storage-box">
                <div className="rail-title"><span>Disco</span><span className="mono">{storage.disk_used_pct}% usado · {storage.disk_free_gb} GB libres</span></div>
                <div className="cost-bar"><span style={{ width: `${Math.min(100, storage.disk_used_pct)}%` }} /></div>
                {storage.disk_warning && <div className="error-text">Disco por encima del umbral de alerta. Corré retención o ampliá el volumen.</div>}
                <div className="muted small">Proyectos: {(storage.projects_bytes / 1024 / 1024).toFixed(1)} MB · Backups: {(storage.backups_bytes / 1024 / 1024).toFixed(1)} MB ({storage.backups_count})</div>
              </div>
            )}
            <div className="backup-actions">
              <button className="btn primary" disabled={backupBusy} onClick={createBackup}>{backupBusy ? "Trabajando…" : "Crear backup ahora"}</button>
              <button className="btn ghost" onClick={previewRetention}>Previsualizar retención</button>
            </div>
            <div className="backup-list">
              {backupList.map((item: any) => (
                <div key={item.name} className="backup-row">
                  <span className="mono">{item.created_at?.slice(0, 19).replace("T", " ")}</span>
                  <span>{(item.size / 1024 / 1024).toFixed(1)} MB · {item.project_count} proyectos</span>
                  <div className="backup-row-actions">
                    <button className="btn tiny" onClick={() => verifyBackup(item.name)}>Verificar</button>
                    <button className="btn tiny" onClick={() => downloadBackup(item.name)}>Descargar</button>
                  </div>
                </div>
              ))}
              {!backupList.length && <p className="muted small">Sin backups todavía.</p>}
            </div>
            {verifyReport && (
              <div className="issued">
                <div className="kicker">VERIFICACIÓN {verifyReport.valid ? "OK" : "CON ERRORES"}</div>
                <pre>{verifyReport.checks.map((check: any) => `${check.ok ? "✓" : "✗"} ${check.name}${check.detail ? ": " + check.detail : ""}`).join("\n")}</pre>
              </div>
            )}
            {retentionReport && (
              <div className="issued">
                <div className="kicker">RETENCIÓN (SIMULACIÓN)</div>
                <pre>{`renders > ${retentionReport.renders_days} días: ${retentionReport.candidate_count}\nliberaría: ${(retentionReport.freed_bytes / 1024 / 1024).toFixed(1)} MB`}</pre>
              </div>
            )}
          </section>
          <div className="settings-actions"><button className="btn primary" onClick={save}>Guardar cambios</button></div>
        </div>
      )}
    </ScreenShell>
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

function OpsScreen({ onBack }: { onBack: () => void }) {
  const [metrics, setMetrics] = useState<any>(null);
  const [alerts, setAlerts] = useState<any>({ enabled: false, webhook_url: "", on_job_failed: true, disk_pct: 80 });
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setMetrics(await api.get("/admin/metrics"));
      setError("");
    } catch (err: any) {
      setError(err.message);
    }
  }, []);
  useEffect(() => {
    void load();
    api.get("/settings").then((payload) => {
      if (payload.alerts) setAlerts({ ...alerts, ...payload.alerts });
    }).catch(() => {});
    const timer = window.setInterval(load, 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  const saveAlerts = async (event: React.FormEvent) => {
    event.preventDefault();
    setStatus("");
    try {
      const payload = await api.put("/settings", { alerts });
      setAlerts({ ...alerts, ...(payload.alerts || {}) });
      setStatus("Alertas guardadas.");
    } catch (err: any) {
      setError(err.message);
    }
  };
  const testAlert = async () => {
    try {
      const result = await api.post("/admin/alerts/test", {});
      setStatus(result.sent ? `Alerta enviada (HTTP ${result.status}).` : `No enviada: ${result.reason || "deshabilitada"}.`);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const jobs = metrics?.jobs;
  return (
    <ScreenShell title="Observabilidad" onBack={onBack}>
      {error && <div className="error-banner">{error}</div>}
      {status && <div className="ok-banner">{status}</div>}
      {!metrics ? <p className="muted">Cargando métricas…</p> : (
        <>
          <div className="ops-cards">
            <div className="ops-card"><span className="kicker">ACTIVOS</span><strong>{jobs.active}</strong><span className="muted small">{jobs.by_status?.queued || 0} en cola</span></div>
            <div className="ops-card"><span className="kicker">ESPERANDO GATE</span><strong>{jobs.awaiting_human}</strong><span className="muted small">requieren aprobación</span></div>
            <div className="ops-card"><span className="kicker">TASA DE ÉXITO</span><strong>{jobs.success_rate_pct}%</strong><span className="muted small">{jobs.total} jobs totales</span></div>
            <div className="ops-card"><span className="kicker">COSTO HOY</span><strong>${Number(metrics.cost.today_usd).toFixed(3)}</strong><span className="muted small">total ${Number(metrics.cost.total_usd).toFixed(3)}</span></div>
            <div className="ops-card"><span className="kicker">DISCO</span><strong>{metrics.storage.disk_used_pct}%</strong><span className="muted small">{metrics.storage.disk_free_gb} GB libres</span></div>
            <div className="ops-card"><span className="kicker">PROYECTOS</span><strong>{metrics.projects.count}</strong><span className="muted small">{metrics.engine.mode} · {metrics.engine.provider}</span></div>
          </div>
          <div className="settings-grid">
            <section className="settings-card wide">
              <div className="kicker">JOBS POR STAGE</div>
              <div className="table stage-table">
                <div className="tr head"><span>Stage</span><span>Jobs</span><span>Duración media</span><span>Costo</span></div>
                {jobs.by_stage.map((row: any) => (
                  <div key={row.stage} className="tr">
                    <span>{row.stage}</span><span>{row.jobs}</span>
                    <span>{row.avg_duration_seconds}s</span>
                    <span className="mono">${row.cost_usd.toFixed(4)}</span>
                  </div>
                ))}
                {!jobs.by_stage.length && <div className="empty-card">Sin jobs todavía.</div>}
              </div>
            </section>
            <section className="settings-card wide">
              <div className="kicker">ALERTAS POR WEBHOOK</div>
              <form className="alerts-form" onSubmit={saveAlerts}>
                <label className="check"><input type="checkbox" checked={!!alerts.enabled} onChange={(event) => setAlerts({ ...alerts, enabled: event.target.checked })} /> Habilitadas</label>
                <input className="input" type="url" placeholder="https://hooks.slack.com/…" value={alerts.webhook_url} onChange={(event) => setAlerts({ ...alerts, webhook_url: event.target.value })} />
                <label className="field inline"><span>Umbral de disco (%)</span><input className="input" type="number" value={alerts.disk_pct} onChange={(event) => setAlerts({ ...alerts, disk_pct: Number(event.target.value) })} /></label>
                <div className="backup-actions">
                  <button className="btn primary">Guardar alertas</button>
                  <button type="button" className="btn ghost" onClick={testAlert}>Probar</button>
                </div>
              </form>
              <p className="muted small">Los jobs fallidos y el disco por encima del umbral disparan el webhook (máx. 1 alerta de disco por día).</p>
            </section>
          </div>
        </>
      )}
    </ScreenShell>
  );
}

function UsersScreen({ onBack }: { onBack: () => void }) {
  const [users, setUsers] = useState<any[]>([]);
  const [tokens, setTokens] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ email: "", name: "", role: "producer", password: "" });
  const [tokenName, setTokenName] = useState("integraciones");
  const [issued, setIssued] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      const [userList, tokenList] = await Promise.all([api.get("/users"), api.get("/tokens")]);
      setUsers(userList.data || []);
      setTokens(tokenList.data || []);
      setError("");
    } catch (err: any) {
      setError(err.message);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const createUser = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await api.post("/users", form);
      setForm({ email: "", name: "", role: "producer", password: "" });
      await load();
    } catch (err: any) {
      setError(err.message);
    }
  };
  const setRole = async (user: any, role: string) => {
    try {
      await api.patch(`/users/${user.id}`, { role });
      await load();
    } catch (err: any) {
      setError(err.message);
    }
  };
  const removeUser = async (user: any) => {
    if (!window.confirm(`¿Eliminar a ${user.email}?`)) return;
    try {
      await api.del(`/users/${user.id}`);
      await load();
    } catch (err: any) {
      setError(err.message);
    }
  };
  const createToken = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const payload = await api.post("/tokens", { name: tokenName });
      setIssued(payload);
      await load();
    } catch (err: any) {
      setError(err.message);
    }
  };
  const removeToken = async (token: any) => {
    if (!window.confirm(`¿Revocar el token ${token.name}?`)) return;
    try {
      await api.del(`/tokens/${token.id}`);
      await load();
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <ScreenShell title="Usuarios y accesos" onBack={onBack}>
      {error && <div className="error-banner">{error}</div>}
      <div className="settings-grid">
        <section className="settings-card wide">
          <div className="kicker">USUARIOS</div>
          <div className="table">
            <div className="tr head"><span>Email</span><span>Nombre</span><span>Rol</span><span>Alta</span><span /></div>
            {users.map((user) => (
              <div key={user.id} className="tr">
                <span>{user.email}</span>
                <span>{user.name || "—"}</span>
                <span>
                  <select className="input select" value={user.role} onChange={(event) => setRole(user, event.target.value)} aria-label={`Rol de ${user.email}`}>
                    {["admin", "producer", "viewer"].map((role) => <option key={role} value={role}>{role}</option>)}
                  </select>
                </span>
                <span className="mono">{(user.created_at || "").slice(0, 10)}</span>
                <button className="btn tiny danger" onClick={() => removeUser(user)}>Eliminar</button>
              </div>
            ))}
          </div>
          <form className="user-form" onSubmit={createUser}>
            <input className="input" placeholder="email" type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} required />
            <input className="input" placeholder="nombre" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
            <select className="input" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>
              {["producer", "viewer", "admin"].map((role) => <option key={role} value={role}>{role}</option>)}
            </select>
            <input className="input" placeholder="contraseña (8+)" type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required />
            <button className="btn primary">Crear usuario</button>
          </form>
        </section>
        <section className="settings-card wide">
          <div className="kicker">API TOKENS</div>
          <div className="table">
            <div className="tr head"><span>Nombre</span><span>Usuario</span><span>Creado</span><span>Último uso</span><span /></div>
            {tokens.map((token) => (
              <div key={token.id} className="tr">
                <span>{token.name}</span>
                <span>{token.email}</span>
                <span className="mono">{(token.created_at || "").slice(0, 10)}</span>
                <span className="mono">{(token.last_used || "—").slice(0, 10)}</span>
                <button className="btn tiny danger" onClick={() => removeToken(token)}>Revocar</button>
              </div>
            ))}
          </div>
          <form className="user-form" onSubmit={createToken}>
            <input className="input" placeholder="nombre del token" value={tokenName} onChange={(event) => setTokenName(event.target.value)} />
            <button className="btn primary">Generar token</button>
          </form>
          {issued && (
            <div className="issued">
              <div className="kicker">COPIALO AHORA — NO SE VUELVE A MOSTRAR</div>
              <pre>{issued.token}</pre>
              <button className="btn tiny" onClick={() => setIssued(null)}>Listo</button>
            </div>
          )}
        </section>
      </div>
    </ScreenShell>
  );
}

function Workspace({ slug, onBack, onLogout }: { slug: string; onBack: () => void; onLogout: () => void }) {
  const [project, setProject] = useState<any>(null);
  const [board, setBoard] = useState<any>(null);
  const [chat, setChat] = useState<any[]>([]);
  const [brief, setBrief] = useState<any>(null);
  const [script, setScript] = useState<any>(null);
  const [assets, setAssets] = useState<any[]>([]);
  const [tab, setTab] = useState("storyboard");
  const [selected, setSelected] = useState<any>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [projectData, boardData, chatData, assetData] = await Promise.all([
        api.get(`/projects/${slug}`),
        api.get(`/projects/${slug}/board`),
        api.get(`/projects/${slug}/chat`),
        api.get(`/projects/${slug}/assets`).catch(() => ({ assets: [] })),
      ]);
      setProject(projectData);
      setBoard(boardData);
      setChat(chatData.data || []);
      setAssets(assetData.assets || []);
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

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName || "");
      if (event.key === "Escape" && selected) { setSelected(null); return; }
      if (typing) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        void api.post(`/projects/${slug}/undo`, {}).then(refresh).catch(() => {});
      }
      if ((event.key === "ArrowRight" || event.key === "ArrowLeft") && board?.scenes?.length) {
        const currentIndex = selected ? board.scenes.findIndex((scene: any) => scene.id === selected.id) : -1;
        const nextIndex = event.key === "ArrowRight" ? Math.min(board.scenes.length - 1, currentIndex + 1) : Math.max(0, currentIndex - 1);
        const next = board.scenes[nextIndex];
        if (next) {
          setSelected(next);
          document.getElementById(`scene-${next.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [board, selected, refresh, slug]);

  const regenerateScene = async (scene: any, instructions: string) => {
    await api.post(`/projects/${slug}/scenes/${scene.id}/regenerate`, { instructions: instructions || `Regenerar ${scene.id}` });
    await refresh();
  };

  if (error && !project) {
    return <ScreenShell title="Error" onBack={onBack}><div className="error-banner">{error}</div></ScreenShell>;
  }
  if (!project || !board) return <div className="page loading">Cargando producción…</div>;

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
          <button className="btn ghost" onClick={onBack} aria-label="Volver a la biblioteca">←</button>
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
              <div key={artifact.name} className="asset-row"><span>{artifact.name}</span><span className={`dot-status ${artifact.valid ? "ok" : "bad"}`} /></div>
            ))}
          </div>
          <div className="sidebar-section">
            <div className="kicker">ACTIVOS</div>
            {assets.slice(0, 8).map((asset: any) => <div key={asset.id} className="asset-row"><span>{asset.type} · {asset.id}</span></div>)}
            {!assets.length && <p className="muted small">Sin activos.</p>}
          </div>
          <div className="sidebar-section">
            <div className="kicker">RENDERS</div>
            {(board.renders || []).map((render: any) => <div key={render.id} className="asset-row"><span>{render.path}</span></div>)}
            {!board.renders?.length && <p className="muted small">Sin renders.</p>}
          </div>
        </aside>
        <main className="board">
          <StageRail stages={board.stages || []} />
          {pendingGate && <GateBar gate={pendingGate} onApprove={approve} onReject={reject} />}
          <div className="tabs" role="tablist" aria-label="Vistas de producción">
            {[["brief", "Brief"], ["script", "Guion"], ["storyboard", "Storyboard"], ["timeline", "Timeline"], ["renders", "Renders"]].map(([key, label]) => (
              <button key={key} role="tab" aria-selected={tab === key} className={`tab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>{label}</button>
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
            {tab === "storyboard" && <Storyboard slug={slug} scenes={board.scenes || []} onRefresh={refresh} onOpen={setSelected} />}
            {tab === "timeline" && <Timeline scenes={board.scenes || []} assets={assets} script={script} />}
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
      {selected && <SceneDrawer scene={selected} onClose={() => setSelected(null)} onRegenerate={regenerateScene} />}
    </div>
  );
}

export default function App() {
  const [token, setTok] = useState(getToken());
  const [user, setUserState] = useState<any>(getUser());
  const [route, setRoute] = useState(window.location.hash || "#/");
  const [booting, setBooting] = useState(true);

  useEffect(() => {
    const onHash = () => setRoute(window.location.hash || "#/");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    (async () => {
      if (token) {
        const ok = await verifyToken(token);
        if (!ok) {
          clearToken();
          setTok("");
          setUserState(null);
        }
      } else {
        const sessionUser = await fetchMe();
        if (sessionUser) setUserState(sessionUser);
      }
      setBooting(false);
    })();
  }, []);

  const logout = () => {
    void logoutSession();
    clearToken();
    setTok("");
    setUserState(null);
    window.location.hash = "#/";
  };

  if (booting) return <div className="page loading">Cargando…</div>;
  if (!token && !user) {
    return <Login onLogin={(next) => { setTok(next); setUserState(null); }} onSession={(next) => { setUserState(next); setTok(""); }} />;
  }
  const slug = route.startsWith("#/p/") ? route.slice(4) : "";
  if (slug) return <Workspace key={slug} slug={slug} onBack={() => (window.location.hash = "#/")} onLogout={logout} />;
  if (route === "#/jobs") return <JobsScreen onBack={() => (window.location.hash = "#/")} onOpenProject={(next) => (window.location.hash = `#/p/${next}`)} />;
  if (route === "#/providers") return <ProvidersScreen onBack={() => (window.location.hash = "#/")} />;
  if (route === "#/settings") return <SettingsScreen onBack={() => (window.location.hash = "#/")} />;
  if (route === "#/ops") return <OpsScreen onBack={() => (window.location.hash = "#/")} />;
  if (route === "#/users") return <UsersScreen onBack={() => (window.location.hash = "#/")} />;
  return <Library onOpen={(next) => (window.location.hash = `#/p/${next}`)} onLogout={logout} user={user} />;
}
