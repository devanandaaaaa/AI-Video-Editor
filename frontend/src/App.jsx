import { useState } from "react";
import "./App.css";
import "./HighFidelity.css";
import "./Home.css";
import "./Dashboard.css";
import "./UploadStatus.css";

const API = "http://127.0.0.1:8000";
const I = {
  spark: "M12 3 13.8 8.2 19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z",
  home: "M3 10.5 12 3l9 7.5V21H3v-10.5ZM9 21v-6h6v6",
  folder: "M3 7h7l2 2h9v10H3V7Z",
  plus: "M12 5v14M5 12h14",
  doc: "M7 3h6l4 4v14H7V3Zm6 0v5h5",
  video: "M4 6h11v12H4V6Zm11 4 5-3v10l-5-3",
  check: "m6 12 3.5 3.5L18 7",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  down: "M12 3v11m0 0 4-4m-4 4-4-4M5 19h14",
};
function Icon({ n, s = 18 }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none">
      <path
        d={I[n]}
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
const empty = { type: "", message: "" };
export default function App() {
  const [view, setView] = useState("home"),
    [script, setScript] = useState(null),
    [videos, setVideos] = useState([]),
    [id, setId] = useState(""),
    [frames, setFrames] = useState(false),
    [beats, setBeats] = useState([]),
    [scenes, setScenes] = useState([]),
    [embed, setEmbed] = useState(null),
    [matches, setMatches] = useState([]),
    [selections, setSelections] = useState([]),
    [render, setRender] = useState(null),
    [load, setLoad] = useState(empty),
    [status, setStatus] = useState(empty);
  const reset = () => {
    setId("");
    setFrames(false);
    setBeats([]);
    setScenes([]);
    setEmbed(null);
    setMatches([]);
    setSelections([]);
    setRender(null);
    setLoad(empty);
    setStatus(empty);
  };
  const url = render?.output_video_path
    ? `${API}/outputs/${render.output_video_path.split("/").map(encodeURIComponent).join("/")}`
    : "";
  const call = async (path, method = "POST", body) => {
    setLoad({ type: "loading", message: "Processing your project..." });
    try {
      const r = await fetch(`${API}${path}`, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      const j = await r.json();
      if (!r.ok) throw Error(j.detail || "Request failed.");
      setLoad({ type: "success", message: "Completed successfully." });
      return j;
    } catch (e) {
      setLoad({
        type: "error",
        message: e.message || "Could not reach the backend.",
      });
      return null;
    }
  };
  const upload = async () => {
    if (!script || !videos.length) {
      setLoad({
        type: "error",
        message: "Choose one script and at least one video clip.",
      });
      return;
    }
    reset();
    setView("workspace");
    setLoad({ type: "loading", message: "Creating your project workspace..." });
    const f = new FormData();
    f.append("script", script);
    videos.forEach((v) => f.append("videos", v));
    try {
      const r = await fetch(`${API}/api/projects/upload`, {
          method: "POST",
          body: f,
        }),
        j = await r.json();
      if (!r.ok) throw Error(j.detail);
      setId(j.project_id);
      setLoad({
        type: "success",
        message: `${j.clip_count} clip(s) uploaded. Project ready.`,
      });
    } catch (e) {
      setLoad({ type: "error", message: e.message || "Upload failed." });
    }
  };
  const action = async (kind) => {
    let j;
    if (kind === "frames") {
      j = await call(`/api/projects/${id}/extract-frames`);
      if (j) setFrames(true);
    }
    if (kind === "beats") {
      j = await call(`/api/projects/${id}/script-beats`, "GET");
      if (j) setBeats(j.beats);
    }
    if (kind === "scenes") {
      j = await call(`/api/projects/${id}/describe-scenes`);
      if (j) setScenes(j.scenes);
    }
    if (kind === "embed") {
      j = await call(`/api/projects/${id}/store-scene-embeddings`);
      if (j) setEmbed(j);
    }
    if (kind === "match") {
      j = await call(`/api/projects/${id}/match-script-beats`);
      if (j) setMatches(j.matches);
    }
    if (kind === "plan") {
      j = await call(`/api/projects/${id}/prepare-rough-cut`, "POST", {
        matches,
      });
      if (j) setSelections(j.selections);
    }
    if (kind === "render") {
      j = await call(`/api/projects/${id}/render-rough-cut`, "POST", {
        selections,
      });
      if (j) {
        setRender(j);
        setView("result");
      }
    }
  };
  const steps = [
    ["Uploading files", !!id],
    ["Extracting frames", frames],
    ["Extracting script beats", !!beats.length],
    ["Understanding scenes", !!scenes.length],
    ["Generating embeddings", !!embed],
    ["Matching scenes", !!matches.length],
    ["Preparing rough cut", !!selections.length],
    ["Rendering video", !!render],
  ];
  const next = !id
    ? null
    : !frames
      ? ["frames", "Extract Frames"]
      : !beats.length
        ? ["beats", "Extract Script Beats"]
        : !scenes.length
          ? ["scenes", "Understand Video Scenes"]
          : !embed
            ? ["embed", "Generate Embeddings"]
            : !matches.length
              ? ["match", "Match Script to Scenes"]
              : !selections.length
                ? ["plan", "Prepare Rough Cut"]
                : !render
                  ? ["render", "Render Rough Cut"]
                  : null;
  const Msg = () =>
    load.message && (
      <p className={`msg ${load.type}`}>
        {load.type === "loading" && <i />}
        {load.message}
      </p>
    );
  const Upload = () => (
    <section className="upload">
      <div>
        <p className="kicker">New project</p>
        <h1>Build your rough cut.</h1>
        <p>
          Select your script and footage. The AI will find visuals for every
          story beat.
        </p>
      </div>
      <div className="uploads">
        <label>
          <input
            type="file"
            accept=".txt"
            onChange={(e) => {
              setScript(e.target.files?.[0] || null);
              reset();
            }}
          />
          <Icon n={script ? "check" : "doc"} />
          <b>Voiceover script</b>
          <strong>{script?.name || "Choose a TXT file"}</strong>
          <small>One script file</small>
        </label>
        <label>
          <input
            type="file"
            accept="video/*"
            multiple
            onChange={(e) => {
              setVideos([...e.target.files]);
              reset();
            }}
          />
          <Icon n={videos.length ? "check" : "video"} />
          <b>Raw video clips</b>
          <strong>
            {videos.length
              ? `${videos.length} clip(s) selected`
              : "Add your footage"}
          </strong>
          <small>
            {videos.length
              ? videos.map((x) => x.name).join(" · ")
              : "MP4, MOV, WEBM"}
          </small>
        </label>
      </div>
      <div className="bar">
        <span>
          <b>Ready when you are</b>
          <small>Files remain in this private session.</small>
        </span>
        <button className="primary" onClick={upload}>
          Create Project <Icon n="arrow" />
        </button>
      </div>
      <Msg />
    </section>
  );
  const Workspace = () => (
    <div className="dash">
      <aside>
        <b>
          <em>
            <Icon n="spark" />
          </em>{" "}
          AI Video Editor
        </b>
        <button className="selected">
          <Icon n="home" />
          Dashboard
        </button>
        <button onClick={() => setView("projects")}>
          <Icon n="folder" />
          Projects
        </button>
        <button
          onClick={() => {
            reset();
            setScript(null);
            setVideos([]);
          }}
        >
          <Icon n="plus" />
          New Project
        </button>
        <button type="button"><Icon n="doc" />Templates</button>
        <button type="button"><Icon n="spark" />Settings</button>
        <button type="button"><Icon n="video" />Support</button>
        <small className="logout">Logout</small>
      </aside>
      <section className="content">
        <header>
          <div>
            <p className="kicker">Dashboard</p>
            <h1>Dashboard</h1>
            <p>Welcome back! Here's an overview of your video projects.</p>
          </div>
          <button className="primary" onClick={() => { reset(); setScript(null); setVideos([]); }}>New Project <Icon n="plus" /></button>
        </header>
        <div className="dashboard-stats"><div><b>{id ? 1 : 0}</b><span>Total Projects</span></div><div><b>{render ? 1 : 0}</b><span>Completed</span></div><div><b>{id && !render ? 1 : 0}</b><span>Processing</span></div><div><b>0</b><span>Failed</span></div></div>
        {!id && <div className="recent-empty"><b>Recent Projects</b><span>No projects yet. Create your first project to see it here.</span></div>}
        {!id ? (
          <Upload />
        ) : (
          <>
            <div className="work">
              <article>
                <p className="kicker">Processing pipeline</p>
                <h2>Your edit, step by step</h2>
                {steps.map(([x, done], i) => (
                  <div className={`step ${done ? "done" : ""}`} key={x}>
                    <span>{done ? <Icon n="check" s={14} /> : i + 1}</span>
                    <b>{x}</b>
                    <small>{done ? "Complete" : "Waiting"}</small>
                  </div>
                ))}
              </article>
              <article className="sidecard">
                <p className="kicker">Progress</p>
                <h2>
                  {steps.filter((x) => x[1]).length} of {steps.length} stages
                </h2>
                <p>Progress is based only on completed processing steps.</p>
              </article>
            </div>
            {next && (
              <div className="bar">
                <span>
                  <b>Next action</b>
                  <small>Continue the real project workflow.</small>
                </span>
                <button
                  className="primary"
                  disabled={load.type === "loading"}
                  onClick={() => action(next[0])}
                >
                  {load.type === "loading" ? "Processing..." : next[1]}{" "}
                  <Icon n="arrow" />
                </button>
              </div>
            )}
            <Msg />
          </>
        )}
      </section>
    </div>
  );
  return (
    <main>
      <nav className="top">
        <button className="logo" onClick={() => setView("home")}>
          <em>
            <Icon n="spark" />
          </em>
          AI Video Editor
        </button>
        <span>
          <button onClick={() => setView("home")}>Home</button>
          <button onClick={() => setView("projects")}>Projects</button>
          <a href="#how">How it works</a>
          <a href="#pricing">Pricing</a>
          <a href="#about">About</a>
          <button className="primary mini" onClick={() => setView("workspace")}>
            Get Started
          </button>
        </span>
      </nav>
      {view === "home" && (
        <>
          <section className="hero">
            <div>
              <p className="kicker">AI-powered video editing</p>
              <h1>
                Turn your script
                <br />
                into a <mark>video.</mark>
              </h1>
              <p>
                Upload your script and raw videos. Our AI analyzes your content,
                matches the best scenes, and creates a rough cut for you.
              </p>
              <button className="primary" onClick={() => setView("workspace")}>
                Create New Project <Icon n="arrow" />
              </button>
            </div>
            <div className="preview">
              <div className="player-top"><span>AI rough cut</span><span>● Ready</span></div>
              <div className="mountains"><i className="mountain one" /><i className="mountain two" /><i className="person" /><button className="play" type="button" aria-label="Decorative preview"><Icon n="arrow" s={25} /></button></div>
              <div className="player-controls"><span>0:00 / 1:28</span><div className="timeline"><i /></div><span>◔ &nbsp; ⛶</span></div>
            </div>
          </section>
          <section className="features" id="how">
            {[
              [
                "doc",
                "AI Scene Understanding",
                "Gemini describes your footage from sampled frames.",
              ],
              [
                "spark",
                "Semantic Matching",
                "Script beats are matched to relevant scenes.",
              ],
              [
                "video",
                "Auto Edit & Export",
                "FFmpeg creates a downloadable rough cut.",
              ],
            ].map((x) => (
              <article key={x[1]}>
                <Icon n={x[0]} />
                <h2>{x[1]}</h2>
                <p>{x[2]}</p>
              </article>
            ))}
          </section>
          <section className="technology-strip" aria-label="Technology used in this project">
            <div><strong>8</strong><span>AI Pipeline Stages</span></div>
            <div><strong>Gemini</strong><span>AI Understanding</span></div>
            <div><strong>Embeddings</strong><span>Gemini + ChromaDB</span></div>
            <div><strong>FFmpeg</strong><span>Video Rendering</span></div>
          </section>
        </>
      )}
      {view === "workspace" && <Workspace />}
      {view === "projects" && (
        <section className="projects">
          <p className="kicker">Projects</p>
          <h1>Your projects</h1>
          {id ? (
            <article>
              <Icon n="video" />
              <span>
                <b>Project {id.slice(0, 8)}</b>
                <small>
                  {render ? "Rough cut rendered" : "Current session project"}
                </small>
              </span>
              <button onClick={() => setView(render ? "result" : "workspace")}>
                Open <Icon n="arrow" />
              </button>
            </article>
          ) : (
            <div className="empty">
              <Icon n="folder" s={28} />
              <h2>No previous projects yet.</h2>
              <p>Projects are available during this browser session.</p>
              <button className="primary" onClick={() => setView("workspace")}>
                Create New Project
              </button>
            </div>
          )}
        </section>
      )}
      {view === "result" && (
        <section className="result">
          <p className="kicker">Export complete</p>
          <h1>Your video is ready.</h1>
          <p>
            {render?.segment_count || 0} selected segments assembled into a{" "}
            {render?.duration_seconds || 0}-second rough cut.
          </p>
          {url && (
            <video
              controls
              src={url}
              onError={() =>
                setLoad({
                  type: "error",
                  message:
                    "Video preview could not load. Confirm the backend is running, then render again.",
                })
              }
            />
          )}
          <Msg />
          <div>
            <a
              className="primary"
              href={url}
              download={
                render?.output_video_path?.split("/").pop() || "rough-cut.mp4"
              }
            >
              <Icon n="down" />
              Download Rough Cut
            </a>
            <button
              onClick={() => {
                reset();
                setScript(null);
                setVideos([]);
                setView("workspace");
              }}
            >
              Create Again
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
