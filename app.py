#!/usr/bin/env python3
"""
LogitLock Frontend  –  Enterprise AI Security Firewall
Streamlit + Microsoft Fluent Design System (dark mode)
"""

import re
import uuid
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st

# ═══════════════════════════════════════════════════════════════════
# 1. PAGE CONFIG   (must be the very first Streamlit call)
# ═══════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="LogitLock",
    page_icon="🔒",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"Get Help": None, "Report a bug": None, "About": None},
)


# ═══════════════════════════════════════════════════════════════════
# 2. CSS INJECTION
# ═══════════════════════════════════════════════════════════════════
def _inject_css() -> None:
    css_path = Path(__file__).parent / "style.css"
    try:
        css = css_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        css = ""
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


_inject_css()


_BANNER = Path(__file__).parent / "logit_lock_darkmode_BANNER.jpg"


# ═══════════════════════════════════════════════════════════════════
# 3. CONSTANTS
# ═══════════════════════════════════════════════════════════════════
_API_URL = (
    "https://logitlock-cng6e9h4crb0c8fs.centralindia-01.azurewebsites.net/chat"
)
_API_TIMEOUT = 30  # seconds


# ═══════════════════════════════════════════════════════════════════
# 4. CACHED RESOURCES  (thread-safe singletons via @st.cache_resource)
# ═══════════════════════════════════════════════════════════════════
@st.cache_resource
def _http_session() -> requests.Session:
    """Single requests.Session reused across all reruns and threads."""
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# ═══════════════════════════════════════════════════════════════════
# 5. SESSION STATE INITIALISATION
# ═══════════════════════════════════════════════════════════════════
def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _blank_workspace(name: str = "New Chat") -> dict:
    return {
        "name": name,
        "messages": [],
        "artifacts": [],
        "created_at": datetime.now().strftime("%b %d, %Y"),
    }


def _init() -> None:
    if "workspaces" not in st.session_state:
        fid = _uid()
        st.session_state.workspaces = {fid: _blank_workspace()}
        st.session_state.active_ws = fid
    if "active_ws" not in st.session_state:
        st.session_state.active_ws = next(iter(st.session_state.workspaces))
    if "show_artifacts" not in st.session_state:
        st.session_state.show_artifacts = False
    if "config" not in st.session_state:
        st.session_state.config = {
            "max_tokens": 1024,
            "sensitivity": "Medium",
        }


_init()


# ═══════════════════════════════════════════════════════════════════
# 6. WORKSPACE ACCESSORS
# ═══════════════════════════════════════════════════════════════════
def _ws() -> dict:
    return st.session_state.workspaces[st.session_state.active_ws]


def _msgs() -> list:
    return _ws()["messages"]


def _arts() -> list:
    return _ws()["artifacts"]


def _push_msg(role: str, content: str, meta: dict | None = None) -> None:
    _ws()["messages"].append(
        {
            "id": _uid(),
            "role": role,
            "content": content,
            "ts": datetime.now().strftime("%H:%M"),
            "meta": meta or {},
        }
    )
    # Auto-title workspace from first user turn
    if role == "user" and len(_msgs()) == 1:
        title = content[:30] + ("…" if len(content) > 30 else "")
        _ws()["name"] = title


def _push_artifact(lang: str, code: str) -> None:
    _ws()["artifacts"].append(
        {
            "id": _uid(),
            "language": lang or "text",
            "code": code,
            "ts": datetime.now().strftime("%H:%M"),
        }
    )


# ═══════════════════════════════════════════════════════════════════
# 7. BUSINESS LOGIC
# ═══════════════════════════════════════════════════════════════════
def _build_history() -> list:
    """Construct conversation_history payload (exclude blocked turns)."""
    return [
        {"role": m["role"], "content": m["content"]}
        for m in _msgs()
        if m["role"] in ("user", "assistant") and not m["meta"].get("blocked")
    ]


def _call_api(message: str, history: list) -> dict:
    """POST to the LogitLock backend and return parsed JSON or an error dict."""
    try:
        r = _http_session().post(
            _API_URL,
            json={"message": message, "conversation_history": history},
            timeout=_API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.Timeout:
        return {"error": "Request timed out — the server may be under load. Please retry."}
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach the LogitLock API. Check your network connection."}
    except requests.exceptions.HTTPError as exc:
        return {"error": f"Server returned HTTP {exc.response.status_code}."}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Unexpected error: {exc}"}


def _extract_code(text: str) -> list[tuple[str, str]]:
    """Return a list of (language, code) tuples from fenced code blocks."""
    return [
        (lang or "text", code.strip())
        for lang, code in re.findall(r"```(\w*)\n?(.*?)```", text, re.DOTALL)
        if code.strip()
    ]


# ═══════════════════════════════════════════════════════════════════
# 8. UI RENDER HELPERS
# ═══════════════════════════════════════════════════════════════════
def _sim_color(score: float) -> str:
    if score < 0.30:
        return "#107c10"  # green  – safe
    if score < 0.60:
        return "#ffb900"  # yellow – caution
    return "#a4262c"      # red    – danger


def _render_sim(score: float | None) -> None:
    if score is None:
        return
    color = _sim_color(score)
    pct = score * 100
    st.markdown(
        f'<div class="ll-sim-bar">'
        f'  <span class="ll-sim-label">Threat similarity</span>'
        f'  <span class="ll-sim-val" style="color:{color}">{pct:.1f}%</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_blocked(threat: str | None, score: float) -> None:
    label = threat or "Suspicious Activity"
    st.markdown(
        f'<div class="ll-threat-card">'
        f'  <div class="ll-threat-header">🛡️&nbsp; Message Blocked</div>'
        f'  <div class="ll-threat-body">'
        f"    This message was flagged by the LogitLock AI security firewall "
        f"    and was not forwarded to the assistant."
        f"  </div>"
        f'  <div class="ll-threat-footer">'
        f'    <span class="ll-threat-tag">{label}</span>'
        f'    <span class="ll-threat-sim">Similarity&nbsp;{score:.1%}</span>'
        f"  </div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_error(msg: str) -> None:
    st.markdown(
        f'<div class="ll-error-card">⚠️&nbsp; {msg}</div>',
        unsafe_allow_html=True,
    )


def _render_message(m: dict) -> None:
    """Render a single persisted message from session state."""
    role = m["role"]
    meta = m["meta"]
    ts = m.get("ts", "")
    avatar = "🧑" if role == "user" else "🔒"

    with st.chat_message(role, avatar=avatar):
        if meta.get("error"):
            _render_error(meta["error"])
        elif meta.get("blocked"):
            _render_blocked(
                meta.get("threat_type"), float(meta.get("similarity_score") or 0)
            )
        else:
            st.markdown(m["content"])
            if role == "assistant":
                _render_sim(meta.get("similarity_score"))

        st.markdown(
            f'<span class="ll-ts">{ts}</span>', unsafe_allow_html=True
        )


# ═══════════════════════════════════════════════════════════════════
# 9. SIDEBAR
# ═══════════════════════════════════════════════════════════════════
with st.sidebar:
    # ── Brand ──────────────────────────────────────────────────────
    st.markdown(
        '<div class="ll-brand">'
        '  <span class="ll-brand-icon">🔒</span>'
        '  <span class="ll-brand-name">LogitLock</span>'
        '  <span class="ll-brand-tag">AI Firewall</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown('<hr class="ll-hr"/>', unsafe_allow_html=True)

    # ── New Chat ────────────────────────────────────────────────────
    if st.button("＋  New Chat", key="btn_new", use_container_width=True):
        wid = _uid()
        st.session_state.workspaces[wid] = _blank_workspace()
        st.session_state.active_ws = wid
        st.session_state.show_artifacts = False
        st.rerun()

    # ── Workspace List ──────────────────────────────────────────────
    st.markdown(
        '<p class="ll-section-label">Conversations</p>', unsafe_allow_html=True
    )

    for wid, wdata in reversed(list(st.session_state.workspaces.items())):
        is_active = wid == st.session_state.active_ws
        label = ("▸ " if is_active else "  ") + wdata["name"]
        btn_type = "primary" if is_active else "secondary"
        if st.button(
            label,
            key=f"ws_{wid}",
            use_container_width=True,
            type=btn_type,
            help=wdata["created_at"],
        ):
            if wid != st.session_state.active_ws:
                st.session_state.active_ws = wid
                st.rerun()

    st.markdown('<hr class="ll-hr"/>', unsafe_allow_html=True)

    # ── Configuration Hub ───────────────────────────────────────────
    with st.expander("⚙️  Configuration", expanded=False):
        sens = st.select_slider(
            "Security Sensitivity",
            options=["Low", "Medium", "High"],
            value=st.session_state.config["sensitivity"],
            key="cfg_sens",
        )
        st.session_state.config["sensitivity"] = sens

        mxt = st.number_input(
            "Max Tokens",
            min_value=128,
            max_value=4096,
            value=int(st.session_state.config["max_tokens"]),
            step=128,
            key="cfg_mxt",
        )
        st.session_state.config["max_tokens"] = int(mxt)

        st.markdown(
            '<p class="ll-config-note">'
            "Model temperature and system prompt are managed by the LogitLock backend."
            "</p>",
            unsafe_allow_html=True,
        )

    # ── Artifacts Toggle ────────────────────────────────────────────
    if _arts():
        st.markdown('<hr class="ll-hr"/>', unsafe_allow_html=True)
        n = len(_arts())
        icon = "✕" if st.session_state.show_artifacts else "📄"
        verb = "Hide" if st.session_state.show_artifacts else "View"
        if st.button(
            f"{icon}  {verb} Artifacts ({n})",
            key="btn_art",
            use_container_width=True,
        ):
            st.session_state.show_artifacts = not st.session_state.show_artifacts
            st.rerun()


# ═══════════════════════════════════════════════════════════════════
# 10. DYNAMIC LAYOUT CONSTRAINT
# ═══════════════════════════════════════════════════════════════════
has_art_panel = bool(_arts()) and st.session_state.show_artifacts

# Override block-container width depending on whether the artifact panel is open
_layout_css = (
    "section[data-testid='stMainBlockContainer']"
    "{ max-width: 100% !important; padding: 0 1.5rem 2rem; }"
    if has_art_panel
    else "section[data-testid='stMainBlockContainer']"
    "{ max-width: 52rem; margin: 0 auto; padding: 0 2rem 2rem; }"
)
st.markdown(f"<style>{_layout_css}</style>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# 11. MAIN LAYOUT   (conditionally two-column when artifacts panel is open)
# ═══════════════════════════════════════════════════════════════════
if has_art_panel:
    chat_col, art_col = st.columns([3, 2], gap="medium")
else:
    chat_col = st.container()
    art_col = None


# ═══════════════════════════════════════════════════════════════════
# 12. CHAT PANEL
# ═══════════════════════════════════════════════════════════════════
with chat_col:
    ws = _ws()

    # Full-bleed banner (rendered as raw HTML to break out of column width)
    if _BANNER.exists():
        import base64
        _img_b64 = base64.b64encode(_BANNER.read_bytes()).decode()
        _ext = _BANNER.suffix.lstrip(".")
        _mime = "image/jpeg" if _ext in ("jpg", "jpeg") else f"image/{_ext}"
        st.markdown(
            f'<div class="ll-banner-wrap">'
            f'<img src="data:{_mime};base64,{_img_b64}" alt="LogitLock Banner"/>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Header
    st.markdown(
        f'<div class="ll-chat-header">'
        f'  <span class="ll-chat-title">{ws["name"]}</span>'
        f'  <span class="ll-chat-date">{ws["created_at"]}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Render persisted message history ──────────────────────────
    if not _msgs():
        st.markdown(
            '<div class="ll-empty">'
            '  <div class="ll-empty-icon">🔒</div>'
            '  <div class="ll-empty-title">LogitLock AI Firewall</div>'
            '  <div class="ll-empty-sub">'
            "    Every message is screened against known threat patterns "
            "    before reaching the assistant. Start a conversation below."
            "  </div>"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        for msg in _msgs():
            _render_message(msg)

    # ── Chat input ─────────────────────────────────────────────────
    if user_input := st.chat_input("Send a message…"):
        # Snapshot history BEFORE appending the new user turn
        hist = _build_history()

        # Persist & immediately render the user message
        _push_msg("user", user_input)
        with st.chat_message("user", avatar="🧑"):
            st.markdown(user_input)
            st.markdown(
                f'<span class="ll-ts">{datetime.now().strftime("%H:%M")}</span>',
                unsafe_allow_html=True,
            )

        # Call the API and render the assistant response
        with st.chat_message("assistant", avatar="🔒"):
            with st.spinner(""):
                data = _call_api(user_input, hist)

            if "error" in data:
                _render_error(data["error"])
                _push_msg("assistant", "", meta={"error": data["error"]})

            elif data.get("blocked"):
                threat = data.get("threat_type")
                sim = float(data.get("similarity_score") or 0)
                _render_blocked(threat, sim)
                _push_msg(
                    "assistant",
                    "",
                    meta={
                        "blocked": True,
                        "threat_type": threat,
                        "similarity_score": sim,
                    },
                )

            else:
                reply = data.get("reply", "")
                sim = data.get("similarity_score")

                st.markdown(reply)
                _render_sim(sim)
                st.markdown(
                    f'<span class="ll-ts">{datetime.now().strftime("%H:%M")}</span>',
                    unsafe_allow_html=True,
                )

                # Persist assistant message
                _push_msg(
                    "assistant",
                    reply,
                    meta={"blocked": False, "similarity_score": sim},
                )

                # Extract code artifacts and open the panel automatically
                for lang, code in _extract_code(reply):
                    _push_artifact(lang, code)
                    st.session_state.show_artifacts = True

        # Rerun to render everything cleanly from session state
        st.rerun()


# ═══════════════════════════════════════════════════════════════════
# 13. ARTIFACTS PANEL
# ═══════════════════════════════════════════════════════════════════
if art_col is not None:
    with art_col:
        arts = _arts()
        st.markdown(
            f'<div class="ll-art-header">'
            f"  Artifacts"
            f'  <span class="ll-art-count">{len(arts)}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
        if arts:
            tab_labels = [
                f"{a['language'].upper()} · {a['ts']}" for a in arts
            ]
            tabs = st.tabs(tab_labels)
            for tab, art in zip(tabs, arts):
                with tab:
                    st.code(art["code"], language=art["language"])
