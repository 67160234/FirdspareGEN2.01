import streamlit as st
import pymysql
import torch
import clip
import numpy as np
import json
import hashlib
from PIL import Image
import faiss
import math
import os
import smtplib
import random
import re
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

st.set_page_config(page_title="FindSpares AI", page_icon="🔧", layout="wide")

# ==================================================
# GLOBAL CSS
# ==================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;900&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Hide Streamlit branding */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 0 !important; }

/* ===== LANDING PAGE ===== */
.landing-wrap {
    min-height: 100vh;
    background: linear-gradient(135deg, #0a0a1a 0%, #0d1b3e 40%, #0a2a4a 70%, #051020 100%);
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    text-align: center; padding: 2rem;
    position: relative; overflow: hidden;
}
.landing-wrap::before {
    content: '';
    position: absolute; inset: 0;
    background: radial-gradient(ellipse at 30% 20%, rgba(255,165,0,0.08) 0%, transparent 60%),
                radial-gradient(ellipse at 70% 80%, rgba(0,120,255,0.08) 0%, transparent 60%);
    pointer-events: none;
}
.landing-badge {
    display: inline-block;
    background: rgba(255,165,0,0.12);
    border: 1px solid rgba(255,165,0,0.3);
    color: #ffa500; font-size: 0.8rem; font-weight: 600;
    padding: 0.35rem 1rem; border-radius: 999px;
    letter-spacing: 0.1em; text-transform: uppercase;
    margin-bottom: 1.5rem;
}
.landing-logo {
    font-size: clamp(3rem, 8vw, 6rem);
    font-weight: 900; line-height: 1;
    background: linear-gradient(135deg, #ffffff 0%, #ffd580 50%, #ffa500 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin-bottom: 0.5rem;
    filter: drop-shadow(0 0 40px rgba(255,165,0,0.3));
}
.landing-sub {
    font-size: clamp(1rem, 2.5vw, 1.4rem);
    color: rgba(255,255,255,0.55); font-weight: 300;
    margin-bottom: 2.5rem; letter-spacing: 0.02em;
}
.landing-features {
    display: flex; gap: 1.5rem; justify-content: center;
    flex-wrap: wrap; margin-bottom: 3rem;
}
.feat-pill {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    color: rgba(255,255,255,0.75);
    padding: 0.5rem 1.2rem; border-radius: 999px;
    font-size: 0.85rem; backdrop-filter: blur(10px);
}
.gear-bg {
    font-size: 8rem; opacity: 0.04;
    position: absolute; top: 8%; right: 5%;
    animation: spin 20s linear infinite;
}
.gear-bg2 {
    font-size: 5rem; opacity: 0.04;
    position: absolute; bottom: 10%; left: 5%;
    animation: spin 30s linear infinite reverse;
}
@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }

/* ===== AUTH PAGE ===== */
.auth-wrap {
    min-height: 100vh;
    background: linear-gradient(135deg, #0a0a1a 0%, #0d1b3e 50%, #051020 100%);
    display: flex; align-items: center; justify-content: center;
    padding: 2rem;
}
.auth-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 20px; padding: 2.5rem;
    width: 100%; max-width: 420px;
    backdrop-filter: blur(20px);
    box-shadow: 0 25px 60px rgba(0,0,0,0.5);
}
.auth-title {
    font-size: 1.8rem; font-weight: 700;
    background: linear-gradient(135deg, #fff 0%, #ffa500 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin-bottom: 0.25rem;
}
.auth-sub { color: rgba(255,255,255,0.45); font-size: 0.9rem; margin-bottom: 2rem; }

/* ===== BUTTON STYLES ===== */
div[data-testid="stButton"] > button {
    border-radius: 12px !important;
    font-weight: 600 !important;
    transition: all 0.2s ease !important;
    border: none !important;
}
div[data-testid="stButton"] > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 25px rgba(255,165,0,0.35) !important;
}

/* Result card */
.part-card {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px; padding: 1rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
}
.part-card:hover { border-color: rgba(255,165,0,0.3); }
.tag-pill {
    display: inline-block;
    background: rgba(255,165,0,0.12);
    color: #ffa500; border-radius: 999px;
    padding: 2px 10px; font-size: 0.75rem;
    margin: 2px;
}
</style>
""", unsafe_allow_html=True)

# ==================================================
# SESSION STATE INIT
# ==================================================
defaults = {
    "nav": "landing",   # landing | auth | main
    "auth_tab": "login",
    "user": None,
    "results": None,
    "search_page": 1,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ==================================================
# DB CONNECTION
# ==================================================
def get_db_connection():
    try:
        if "DB_HOST" not in st.secrets:
            st.error("❌ ไม่พบ DB secrets")
            st.stop()
        return pymysql.connect(
            host=st.secrets["DB_HOST"],
            user=st.secrets["DB_USER"],
            password=st.secrets["DB_PASSWORD"],
            database=st.secrets["DB_NAME"],
            port=int(st.secrets.get("DB_PORT", 3306)),
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10
        )
    except Exception as e:
        st.error(f"❌ DB Error: {e}")
        st.stop()

# ==================================================
# CLIP MODEL (cached)
# ==================================================
device = "cuda" if torch.cuda.is_available() else "cpu"

@st.cache_resource
def load_clip_model():
    m, p = clip.load("ViT-B/32", device=device)
    return m, p

model, preprocess = load_clip_model()

# ==================================================
# VECTORS (cached)
# ==================================================
@st.cache_resource
def load_vectors_cached():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sp.id, sp.part_name, sp.image,
               sp.description, sp.function_tags,
               s.shop_name, s.latitude, s.longitude, s.google_map_link,
               pe.embedding
        FROM part_embeddings pe
        JOIN shop_parts sp ON pe.part_id = sp.id
        JOIN shops s ON sp.shop_id = s.id
    """)
    data = cursor.fetchall()
    conn.close()
    if not data:
        return None, []
    vectors, items = [], []
    for d in data:
        vec = np.array(json.loads(d["embedding"])).astype("float32")
        vec /= np.linalg.norm(vec)
        vectors.append(vec)
        items.append(d)
    vectors = np.array(vectors)
    idx = faiss.IndexFlatIP(vectors.shape[1])
    idx.add(vectors)
    return idx, items

# ==================================================
# HELPERS
# ==================================================
def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def distance(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def translate_keyword(keyword):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT part_name FROM part_synonyms
            WHERE synonym LIKE %s ORDER BY LENGTH(synonym) DESC LIMIT 5
        """, ("%" + keyword + "%",))
        rows = cursor.fetchall()
        if rows:
            parts = list(dict.fromkeys([r["part_name"] for r in rows]))
            conn.close()
            return " ".join(parts)
        words = keyword.split()
        found = []
        for w in words:
            if len(w) < 2: continue
            cursor.execute("""
                SELECT part_name FROM part_synonyms
                WHERE synonym LIKE %s ORDER BY LENGTH(synonym) DESC LIMIT 1
            """, ("%" + w + "%",))
            r = cursor.fetchone()
            if r and r["part_name"] not in found:
                found.append(r["part_name"])
        conn.close()
        return " ".join(found) + " " + keyword if found else keyword
    except:
        return keyword

def encode_text(text):
    tokens = clip.tokenize([text], truncate=True).to(device)
    with torch.no_grad():
        vec = model.encode_text(tokens)
    vec /= vec.norm(dim=-1, keepdim=True)
    return vec.cpu().numpy().astype("float32")

def encode_image(img):
    img_p = preprocess(img).unsqueeze(0).to(device)
    with torch.no_grad():
        vec = model.encode_image(img_p)
    vec /= vec.norm(dim=-1, keepdim=True)
    return vec.cpu().numpy().astype("float32")

def search(query_vec, user_lat, user_lng, threshold=0.20):
    faiss_index, items = load_vectors_cached()
    if faiss_index is None:
        return []
    D, I = faiss_index.search(query_vec, 200)
    results, seen = [], set()
    for score, i in zip(D[0], I[0]):
        item = items[i]
        if item["id"] in seen: continue
        seen.add(item["id"])
        score = float(max(0, min(1, score)))
        if score < threshold: continue
        dist = distance(user_lat, user_lng, item["latitude"], item["longitude"])
        results.append({
            "part_name": item["part_name"],
            "image": item["image"],
            "description": item.get("description") or "",
            "function_tags": item.get("function_tags") or "",
            "shop_name": item["shop_name"],
            "distance": dist, "score": score,
            "map": item["google_map_link"],
        })
    return results

# ==================================================
# AUTH FUNCTIONS — Email OTP System
# ==================================================

def is_valid_email(email):
    return bool(re.match(r'^[\w\.-]+@[\w\.-]+\.\w{2,}$', email))

def send_otp_email(to_email, otp, purpose="register"):
    """ส่ง OTP ไปยังอีเมลจริงผ่าน SMTP"""
    try:
        smtp_host = st.secrets.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(st.secrets.get("SMTP_PORT", 587))
        smtp_user = st.secrets["SMTP_USER"]
        smtp_pass = st.secrets["SMTP_PASSWORD"]

        subject = "🔧 FindSpares — ยืนยันอีเมลของคุณ" if purpose == "register" else "🔧 FindSpares — รีเซ็ตรหัสผ่าน"
        action  = "สมัครสมาชิก" if purpose == "register" else "รีเซ็ตรหัสผ่าน"

        html = f"""
        <div style="font-family:Inter,sans-serif;max-width:480px;margin:auto;
                    background:#0d1b3e;color:#fff;border-radius:16px;overflow:hidden;">
            <div style="background:linear-gradient(135deg,#1a3a6e,#0a2a4a);
                        padding:2rem;text-align:center;">
                <div style="font-size:2rem;font-weight:900;
                            background:linear-gradient(135deg,#fff,#ffa500);
                            -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
                    🔧 FindSpares
                </div>
            </div>
            <div style="padding:2rem;text-align:center;">
                <p style="color:rgba(255,255,255,0.7);">รหัส OTP สำหรับ{action}</p>
                <div style="font-size:3rem;font-weight:900;letter-spacing:0.3em;
                            color:#ffa500;margin:1.5rem 0;">{otp}</div>
                <p style="color:rgba(255,255,255,0.45);font-size:0.85rem;">
                    รหัสนี้ใช้ได้ภายใน <strong>10 นาที</strong><br>
                    หากคุณไม่ได้ทำรายการนี้ กรุณาเพิกเฉย
                </p>
            </div>
        </div>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"FindSpares AI <{smtp_user}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"❌ ส่งอีเมลไม่สำเร็จ: {e}")
        return False

def save_otp(email, otp, purpose="register"):
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        # ลบ OTP เก่าของ email นี้
        cur.execute("DELETE FROM otp_tokens WHERE email=%s AND purpose=%s", (email, purpose))
        expires = datetime.now() + timedelta(minutes=10)
        cur.execute(
            "INSERT INTO otp_tokens (email, otp_code, purpose, expires_at) VALUES (%s,%s,%s,%s)",
            (email, str(otp), purpose, expires)
        )
        conn.commit(); conn.close()
        return True
    except:
        return False

def verify_otp(email, otp_input, purpose="register"):
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT id FROM otp_tokens
            WHERE email=%s AND otp_code=%s AND purpose=%s
              AND used=0 AND expires_at > NOW()
            ORDER BY id DESC LIMIT 1
        """, (email, str(otp_input).strip(), purpose))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE otp_tokens SET used=1 WHERE id=%s", (row["id"],))
            conn.commit()
        conn.close()
        return row is not None
    except:
        return False

def db_register(email, display_name, password):
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, email, password, display_name, is_verified) VALUES (%s,%s,%s,%s,1)",
            (email, email, hash_pw(password), display_name)
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        return {"id": user_id, "username": display_name or email}
    except pymysql.IntegrityError:
        return "duplicate"
    except:
        return False

def db_login(email, password):
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "SELECT id, display_name, email, is_verified FROM users WHERE email=%s AND password=%s",
            (email, hash_pw(password))
        )
        user = cur.fetchone()
        conn.close()
        return user
    except:
        return None

def db_reset_password(email, new_password):
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("UPDATE users SET password=%s WHERE email=%s", (hash_pw(new_password), email))
        conn.commit(); conn.close()
        return cur.rowcount > 0
    except:
        return False

def db_email_exists(email):
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        r = cur.fetchone(); conn.close()
        return r is not None
    except:
        return False


# ==================================================
# PAGE: LANDING
# ==================================================
def page_landing():
    st.markdown("""
    <div class="landing-wrap">
        <div class="gear-bg">⚙️</div>
        <div class="gear-bg2">🔩</div>
        <div class="landing-badge">🔧 AI-Powered Spare Parts</div>
        <div class="landing-logo">FindSpares</div>
        <div class="landing-sub">ค้นหาอะไหล่รถยนต์ด้วย AI · รวดเร็ว · แม่นยำ · ใกล้คุณ</div>
        <div class="landing-features">
            <span class="feat-pill">🤖 CLIP AI Search</span>
            <span class="feat-pill">📷 ค้นหาด้วยรูปภาพ</span>
            <span class="feat-pill">📍 ร้านใกล้คุณ</span>
            <span class="feat-pill">🔤 ค้นหาจากหน้าที่อะไหล่</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        if st.button("🚀  เริ่มต้นใช้งาน", use_container_width=True,
                     type="primary"):
            st.session_state.nav = "auth"
            st.rerun()

# ==================================================
# PAGE: AUTH (Login / Register / OTP)
# ==================================================
def page_auth():
    st.markdown("""
    <div style="min-height:100vh; background:linear-gradient(135deg,#0a0a1a,#0d1b3e,#051020);
                display:flex; align-items:center; justify-content:center; padding:2rem;">
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.3, 1])
    with col2:
        # Header
        st.markdown("""
        <div style="text-align:center; margin-bottom:1.5rem;">
            <div style="font-size:2.5rem; font-weight:900;
                        background:linear-gradient(135deg,#fff,#ffa500);
                        -webkit-background-clip:text; -webkit-text-fill-color:transparent;">
                🔧 FindSpares
            </div>
            <div style="color:rgba(255,255,255,0.45); font-size:0.9rem; margin-top:0.25rem;">
                ระบบยืนยันตัวตนด้วยอีเมลจริง (Email OTP Authentication)
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Check SMTP settings in Secrets
        has_smtp = "SMTP_USER" in st.secrets and "SMTP_PASSWORD" in st.secrets

        tab_login, tab_reg, tab_reset = st.tabs(["🔑 เข้าสู่ระบบ", "✨ สมัครสมาชิก (OTP)", "🔒 ลืมรหัสผ่าน"])

        # --------------------------------------------------
        # 1. LOGIN TAB
        # --------------------------------------------------
        with tab_login:
            with st.form("login_form"):
                login_email = st.text_input("อีเมล", placeholder="example@email.com", key="l_email")
                login_pw = st.text_input("รหัสผ่าน", type="password", placeholder="กรอกรหัสผ่าน", key="l_pw")
                submitted = st.form_submit_button("เข้าสู่ระบบ", use_container_width=True, type="primary")

                if submitted:
                    if not login_email or not login_pw:
                        st.warning("⚠️ กรุณากรอกอีเมลและรหัสผ่าน")
                    else:
                        with st.spinner("กำลังตรวจสอบข้อมูล..."):
                            user = db_login(login_email.strip(), login_pw)
                        if user:
                            disp_name = user.get("display_name") or user.get("email") or "ผู้ใช้งาน"
                            st.session_state.user = {"id": user["id"], "username": disp_name, "email": user.get("email")}
                            st.session_state.nav = "main"
                            st.success(f"🎉 ยินดีต้อนรับ {disp_name}!")
                            st.rerun()
                        else:
                            st.error("❌ อีเมลหรือรหัสผ่านไม่ถูกต้อง")

            st.markdown("<div style='text-align:center; margin-top:0.5rem;'>", unsafe_allow_html=True)
            if st.button("ดำเนินการต่อในฐานะผู้เยี่ยมชม →", use_container_width=True, key="btn_guest"):
                st.session_state.user = {"id": None, "username": "ผู้เยี่ยมชม", "email": None}
                st.session_state.nav = "main"
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        # --------------------------------------------------
        # 2. REGISTER TAB (Email OTP)
        # --------------------------------------------------
        with tab_reg:
            if "reg_step" not in st.session_state:
                st.session_state.reg_step = 1  # 1: Info form, 2: OTP verify

            if st.session_state.reg_step == 1:
                st.markdown("<div style='font-weight:600; margin-bottom:0.5rem;'>ขั้นตอนที่ 1: กรอกข้อมูลสมัครสมาชิก</div>", unsafe_allow_html=True)
                r_email = st.text_input("อีเมล (เพื่อรับรหัส OTP)", placeholder="yourname@gmail.com", key="r_email")
                r_name = st.text_input("ชื่อผู้ใช้งาน (Display Name)", placeholder="เช่น สมชาย สายลุย", key="r_name")
                r_pw = st.text_input("รหัสผ่าน", type="password", placeholder="อย่างน้อย 6 ตัวอักษร", key="r_pw")
                r_pw2 = st.text_input("ยืนยันรหัสผ่าน", type="password", placeholder="พิมพ์รหัสผ่านอีกครั้ง", key="r_pw2")

                if st.button("📩 ส่งรหัส OTP ไปยังอีเมล", use_container_width=True, type="primary", key="btn_send_reg_otp"):
                    email_clean = r_email.strip()
                    if not all([email_clean, r_name, r_pw, r_pw2]):
                        st.warning("⚠️ กรุณากรอกข้อมูลให้ครบทุกช่อง")
                    elif not is_valid_email(email_clean):
                        st.error("❌ รูปแบบอีเมลไม่ถูกต้อง")
                    elif r_pw != r_pw2:
                        st.error("❌ รหัสผ่านทั้งสองช่องไม่ตรงกัน")
                    elif len(r_pw) < 6:
                        st.warning("⚠️ รหัสผ่านต้องมีความยาวอย่างน้อย 6 ตัวอักษร")
                    elif db_email_exists(email_clean):
                        st.error("❌ อีเมลนี้ถูกลงทะเบียนแล้ว กรุณาเข้าสู่ระบบ")
                    else:
                        otp_code = f"{random.randint(100000, 999999)}"
                        save_otp(email_clean, otp_code, purpose="register")

                        with st.spinner(f"📧 กำลังส่ง OTP ไปที่ {email_clean}..."):
                            if has_smtp:
                                sent = send_otp_email(email_clean, otp_code, purpose="register")
                            else:
                                sent = True
                                st.info(f"💡 [โหมดทดสอบ - ยังไม่ได้ตั้งค่า SMTP] รหัส OTP ของคุณคือ: **{otp_code}**")

                        if sent:
                            st.session_state.reg_data = {
                                "email": email_clean,
                                "name": r_name.strip(),
                                "pw": r_pw
                            }
                            st.session_state.reg_step = 2
                            st.success(f"✅ ส่งรหัส OTP ไปยัง {email_clean} เรียบร้อยแล้ว")
                            st.rerun()

            elif st.session_state.reg_step == 2:
                reg_info = st.session_state.get("reg_data", {})
                target_email = reg_info.get("email", "")

                st.info(f"✉️ ระบบส่งรหัส OTP 6 หลักไปที่: **{target_email}** (หมดอายุใน 10 นาที)")

                otp_input = st.text_input("กรอกรหัส OTP (6 หลัก)", max_chars=6, placeholder="123456", key="reg_otp_input")

                col_v1, col_v2 = st.columns(2)
                with col_v1:
                    if st.button("✅ ยืนยัน OTP & สมัคร", use_container_width=True, type="primary"):
                        if not otp_input or len(otp_input) != 6:
                            st.warning("⚠️ กรุณากรอกรหัส OTP ให้ครบ 6 หลัก")
                        else:
                            with st.spinner("กำลังตรวจสอบ OTP..."):
                                is_ok = verify_otp(target_email, otp_input, purpose="register")
                            if is_ok:
                                res = db_register(target_email, reg_info["name"], reg_info["pw"])
                                if isinstance(res, dict):
                                    st.success("🎉 สมัครสมาชิกและยืนยันอีเมลสำเร็จแล้ว!")
                                    st.session_state.user = res
                                    st.session_state.reg_step = 1
                                    st.session_state.nav = "main"
                                    st.rerun()
                                elif res == "duplicate":
                                    st.error("❌ อีเมลนี้ถูกใช้สมัครไปแล้ว")
                                else:
                                    st.error("❌ เกิดข้อผิดพลาดในการบันทึกข้อมูล")
                            else:
                                st.error("❌ รหัส OTP ไม่ถูกต้อง หรือหมดอายุแล้ว")

                with col_v2:
                    if st.button("← แก้ไขข้อมูล / ขอ OTP ใหม่", use_container_width=True):
                        st.session_state.reg_step = 1
                        st.rerun()

        # --------------------------------------------------
        # 3. FORGOT PASSWORD TAB (OTP Reset)
        # --------------------------------------------------
        with tab_reset:
            if "reset_step" not in st.session_state:
                st.session_state.reset_step = 1

            if st.session_state.reset_step == 1:
                st.caption("กรอกอีเมลของคุณเพื่อรับรหัส OTP สำหรับตั้งรหัสผ่านใหม่")
                reset_email = st.text_input("อีเมลที่เคยลงทะเบียน", placeholder="yourname@gmail.com", key="reset_email_input")

                if st.button("📩 ส่ง OTP รีเซ็ตรหัสผ่าน", use_container_width=True, type="primary", key="btn_send_reset_otp"):
                    em_clean = reset_email.strip()
                    if not em_clean or not is_valid_email(em_clean):
                        st.warning("⚠️ กรุณากรอกอีเมลให้ถูกต้อง")
                    elif not db_email_exists(em_clean):
                        st.error("❌ ไม่พบอีเมลนี้ในระบบ")
                    else:
                        otp_code = f"{random.randint(100000, 999999)}"
                        save_otp(em_clean, otp_code, purpose="reset")

                        with st.spinner(f"📧 กำลังส่ง OTP ไปยัง {em_clean}..."):
                            if has_smtp:
                                sent = send_otp_email(em_clean, otp_code, purpose="reset")
                            else:
                                sent = True
                                st.info(f"💡 [โหมดทดสอบ - ยังไม่ได้ตั้งค่า SMTP] รหัส OTP ของคุณคือ: **{otp_code}**")

                        if sent:
                            st.session_state.reset_target_email = em_clean
                            st.session_state.reset_step = 2
                            st.success(f"✅ ส่ง OTP ไปยัง {em_clean} แล้ว")
                            st.rerun()

            elif st.session_state.reset_step == 2:
                target_em = st.session_state.get("reset_target_email", "")
                st.info(f"🔑 ตั้งรหัสผ่านใหม่สำหรับ: **{target_em}**")

                rst_otp = st.text_input("รหัส OTP 6 หลัก", max_chars=6, placeholder="123456", key="rst_otp")
                new_pw1 = st.text_input("รหัสผ่านใหม่", type="password", placeholder="อย่างน้อย 6 ตัวอักษร", key="rst_pw1")
                new_pw2 = st.text_input("ยืนยันรหัสผ่านใหม่", type="password", placeholder="พิมพ์รหัสผ่านอีกครั้ง", key="rst_pw2")

                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    if st.button("💾 บันทึกรหัสผ่านใหม่", use_container_width=True, type="primary"):
                        if not rst_otp or len(rst_otp) != 6:
                            st.warning("⚠️ กรุณากรอก OTP 6 หลัก")
                        elif not new_pw1 or len(new_pw1) < 6:
                            st.warning("⚠️ รหัสผ่านใหม่ต้องมีอย่างน้อย 6 ตัวอักษร")
                        elif new_pw1 != new_pw2:
                            st.error("❌ รหัสผ่านใหม่ไม่ตรงกัน")
                        else:
                            with st.spinner("กำลังเปลี่ยนรหัสผ่าน..."):
                                if verify_otp(target_em, rst_otp, purpose="reset"):
                                    if db_reset_password(target_em, new_pw1):
                                        st.success("🎉 เปลี่ยนรหัสผ่านสำเร็จ! กรุณาเข้าสู่ระบบด้วยรหัสผ่านใหม่")
                                        st.session_state.reset_step = 1
                                    else:
                                        st.error("❌ เปลี่ยนรหัสผ่านไม่สำเร็จ")
                                else:
                                    st.error("❌ รหัส OTP ไม่ถูกต้องหรือหมดอายุ")

                with col_r2:
                    if st.button("ย้อนกลับ", use_container_width=True, key="btn_back_reset"):
                        st.session_state.reset_step = 1
                        st.rerun()

        # Back button
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← กลับหน้าแรก", use_container_width=True):
            st.session_state.nav = "landing"
            st.rerun()


# ==================================================
# PAGE: MAIN SEARCH
# ==================================================
def page_main():
    # Navbar
    user_name = st.session_state.user["username"] if st.session_state.user else "ผู้เยี่ยมชม"
    col_logo, col_space, col_user = st.columns([2, 5, 2])
    with col_logo:
        st.markdown("""
        <div style="padding:1rem 0; font-size:1.4rem; font-weight:800;
                    background:linear-gradient(135deg,#fff,#ffa500);
                    -webkit-background-clip:text; -webkit-text-fill-color:transparent;">
            🔧 FindSpares
        </div>""", unsafe_allow_html=True)
    with col_user:
        st.markdown(f"""
        <div style="padding:1.1rem 0; text-align:right;
                    color:rgba(255,255,255,0.6); font-size:0.85rem;">
            👤 {user_name}
        </div>""", unsafe_allow_html=True)
    if col_user.button("ออกจากระบบ", key="logout"):
        st.session_state.user = None
        st.session_state.nav = "landing"
        st.session_state.results = None
        st.rerun()

    st.divider()

    # Load vectors
    with st.spinner("📦 กำลังโหลดข้อมูลอะไหล่..."):
        faiss_index, items = load_vectors_cached()
    if faiss_index is None:
        st.warning("⚠️ ไม่พบข้อมูลเวกเตอร์ในฐานข้อมูล")
        return

    # Location (demo)
    user_lat, user_lng = 13.2839215, 100.9289055

    # Search UI
    st.markdown("### 🔍 ค้นหาอะไหล่")
    st.caption("พิมพ์ชื่ออะไหล่ หรือบอกลักษณะ/หน้าที่ เช่น 'กรองอากาศ', 'ระบายความร้อน', 'ลดแรงกระแทก'")

    col1, col2 = st.columns([3, 2])
    with col1:
        query = st.text_input("คำค้นหา", placeholder="เช่น กรองอากาศ, ดูดน้ำมัน, หยุดรถ...", label_visibility="collapsed")
    with col2:
        upload = st.file_uploader("อัปโหลดรูปภาพ", label_visibility="collapsed", type=["jpg","jpeg","png","webp"])

    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        search_btn = st.button("🚀 ค้นหาด้วย AI", use_container_width=True, type="primary")
    with col_clear:
        if st.button("🗑️ ล้าง", use_container_width=True):
            st.session_state.results = None
            st.session_state.search_page = 1
            st.rerun()

    if search_btn:
        st.session_state.search_page = 1
        with st.spinner("🔎 AI กำลังประมวลผล..."):
            if upload:
                img = Image.open(upload)
                query_vec = encode_image(img)
            elif query.strip():
                query_text = translate_keyword(query)
                query_vec = encode_text(query_text)
            else:
                st.warning("⚠️ กรุณาพิมพ์คำค้นหา หรืออัปโหลดรูปภาพ")
                st.stop()

            results = search(query_vec, user_lat, user_lng, threshold=0.20)
            results = sorted(results, key=lambda x: (-x["score"], x["distance"]))
            st.session_state.results = results

        if not results:
            st.info("🔍 ไม่พบอะไหล่ที่ตรงกัน ลองใช้คำอื่น เช่น 'กรองอากาศ', 'ระบายความร้อน'")

    # Results
    if st.session_state.results:
        results = st.session_state.results
        per_page = 9
        page = st.session_state.search_page
        total_pages = math.ceil(len(results) / per_page)
        page_results = results[(page-1)*per_page : page*per_page]

        st.markdown(f"<div style='color:rgba(255,255,255,0.45); font-size:0.85rem; margin-bottom:1rem;'>พบ {len(results)} รายการ</div>", unsafe_allow_html=True)
        cols = st.columns(3)
        for i, r in enumerate(page_results):
            with cols[i % 3]:
                img_path = f"shop_parts/{r['image']}"
                if r["image"] and os.path.exists(img_path):
                    st.image(img_path, use_container_width=True)
                else:
                    st.image("https://via.placeholder.com/300x200?text=No+Image", use_container_width=True)

                st.markdown(f"**{r['part_name']}**")
                if r.get("description"):
                    st.caption(f"📝 {r['description'][:80]}{'...' if len(r['description'])>80 else ''}")
                if r.get("function_tags"):
                    tags = [t.strip() for t in r["function_tags"].split(",") if t.strip()][:4]
                    st.markdown(" ".join([f"`{t}`" for t in tags]))
                st.write(f"🏪 {r['shop_name']}  |  📍 {r['distance']:.1f} กม.  |  ⭐ {r['score']:.2f}")
                st.markdown(f"[🗺️ ดูแผนที่]({r['map']})")
                st.divider()

        # Pagination
        if total_pages > 1:
            p1, p2, p3 = st.columns([1, 2, 1])
            with p1:
                if st.button("⬅️ ก่อนหน้า") and page > 1:
                    st.session_state.search_page -= 1
                    st.rerun()
            with p2:
                st.write(f"หน้า {page} / {total_pages}")
            with p3:
                if st.button("ถัดไป ➡️") and page < total_pages:
                    st.session_state.search_page += 1
                    st.rerun()

# ==================================================
# ROUTER
# ==================================================
nav = st.session_state.nav

if nav == "landing":
    page_landing()
elif nav == "auth":
    page_auth()
elif nav == "main":
    page_main()