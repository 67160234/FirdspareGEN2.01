import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import clip
import torch
from PIL import Image
import faiss
import math
import os
import hashlib
import json
import smtplib
import random
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from supabase import create_client, Client

st.set_page_config(page_title="FindSpares AI (Cloud)", layout="wide", initial_sidebar_state="collapsed")

# ---------------------------
# SESSION STATE INIT (MUST BE AT TOP)
# ---------------------------
if "has_started" not in st.session_state:
    st.session_state.has_started = False
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = None
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "page" not in st.session_state:
    st.session_state.page = 1
if "show_camera" not in st.session_state:
    st.session_state.show_camera = False
if "reg_step" not in st.session_state:
    st.session_state.reg_step = 1  # 1 = form, 2 = otp verify
if "reg_pending" not in st.session_state:
    st.session_state.reg_pending = {}

# ---------------------------
# SEARCH SYNONYMS (SMART SEARCH)
# ---------------------------
SYNONYM_MAP = {
    "Brake Pad": ["เบรก", "เบรค", "ผ้าเบรก", "ผ้าเบรค", "ก้ามเบรก", "เบรกหน้า", "เบรกหลัง", "Brake Pad", "Brake Pads", "Brakepads"],
    "Car Battery": ["แบตเตอรี่", "แบต", "แบตรถยนต์", "ไฟฟ้ารถ", "ขั้วแบต", "น้ำกลั่น", "Car Battery", "Battery", "Accu", "Car Batt"],
    "Air Filter": ["กรองอากาศ", "กรองเครื่อง", "กรอง", "ไส้กรอง", "กรองฝุ่น", "กรองแอร์", "Air Filter", "Air Filters", "Filter", "Air Filter Element"],
    "Ball Joint": ["ลูกหมาก", "ลูกหมากปีกนก", "ลูกหมากแร็ค", "ช่วงล่าง", "ลูกหมากล่าง", "ลูกหมากบน", "คันชัก", "Ball Joint", "Ball Joints", "Suspension Joint"],
    "Brake Disc": ["จานเบรก", "จานเบรค", "จาน", "จานดิส", "เบรกจาน", "จานดิสก์", "Brake Disc", "Brake Discs", "Disc Brake", "Rotor"],
    "Radiator": ["หม้อน้ำ", "ระบายความร้อน", "พัดลมหม้อน้ำ", "ฝาหม้อน้ำ", "ท่อน้ำ", "รังผึ้งหม้อน้ำ", "น้ำยาหล่อเย็น", "Radiator", "Radiators", "Cooling System"],
    "Shock Absorber": ["โช้ค", "โช๊ค", "โช้คอัพ", "สปริง", "ช่วงล่าง", "Shock Absorber", "Shock Absorbers", "Shock", "Shocks", "Strut", "Struts"],
    "Spark Plug": ["หัวเทียน", "คอยล์จุดระเบิด", "จุดระเบิด", "ไฟแปลบ", "หัวเทียนเข็ม", "หัวเทียนรถ", "Spark Plug", "Spark Plugs", "Plug", "Ignition Plug"],
    "Starter Motor": ["ไดสตาร์ท", "มอเตอร์สตาร์ท", "สตาร์ทรถ", "ไดสตาร์ทรถ", "มอเตอร์สตาร์ทรถ", "Starter Motor", "Starter", "Starters", "Ignition Starter"],
    "AC Compressor": ["คอมแอร์", "คอมเพรสเซอร์", "แอร์รถยนต์", "ทำความเย็น", "น้ำยาแอร์", "ท่อแอร์", "AC Compressor", "Compressor", "Air Con", "AC Unit"]
}

# ---------------------------
# DATABASE CONFIG (SUPABASE FALLBACK TO SQLITE)
# ---------------------------
SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)

if USE_SUPABASE:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    st.sidebar.warning("💾 Using local SQLite (Session only). Use Supabase for permanent storage.")

SALT = "FindSparesAI_2024"

def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def hash_pw(password):
    return hashlib.sha256((password + SALT).encode()).hexdigest()

def verify_user(username, password):
    try:
        pw_hash = hash_pw(password)
        if USE_SUPABASE:
            res = supabase.table("users").select("id").eq("username", username).eq("password", pw_hash).execute()
            if res.data: return res.data[0]["id"]
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, email TEXT, password TEXT)")
            cursor.execute("SELECT id FROM users WHERE username = ? AND password = ?", (username, pw_hash))
            row = cursor.fetchone()
            conn.close()
            if row: return row["id"]
    except Exception as e:
        st.error(f"❌ ระบบยืนยันตัวตนผิดพลาด: {e}")
    return None

def add_user(username, email, password):
    try:
        pw_hash = hash_pw(password)
        if USE_SUPABASE:
            res = supabase.table("users").insert({"username": username, "email": email, "password": pw_hash}).execute()
            return True
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, email TEXT, password TEXT)")
            cursor.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)", (username, email, pw_hash))
            conn.commit(); conn.close()
            return True
    except Exception as e:
        if "UNIQUE" in str(e) or "duplicate" in str(e).lower():
            st.warning("⚠️ มีชื่อผู้ใช้นี้อยู่ในระบบแล้ว")
        else:
            st.error(f"❌ ไม่สามารถบันทึกข้อมูลได้: {e}")
        return False

# ---------------------------
# OTP FUNCTIONS
# ---------------------------
def _ensure_otp_table():
    """Create otp_tokens table in SQLite if not exists."""
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS otp_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        )
    """)
    conn.commit(); conn.close()

def save_otp(email, otp_code):
    """Save OTP to database, invalidate old ones."""
    expires = (datetime.utcnow() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        if USE_SUPABASE:
            supabase.table("otp_tokens").delete().eq("email", email).eq("used", 0).execute()
            supabase.table("otp_tokens").insert({"email": email, "otp_code": str(otp_code), "expires_at": expires, "used": 0}).execute()
        else:
            _ensure_otp_table()
            conn = get_db_connection()
            conn.execute("DELETE FROM otp_tokens WHERE email = ? AND used = 0", (email,))
            conn.execute("INSERT INTO otp_tokens (email, otp_code, expires_at, used) VALUES (?, ?, ?, 0)", (email, str(otp_code), expires))
            conn.commit(); conn.close()
        return True
    except Exception as e:
        st.error(f"❌ บันทึก OTP ไม่สำเร็จ: {e}"); return False

def verify_otp(email, otp_input):
    """Verify OTP code. Returns True if valid and not expired."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        if USE_SUPABASE:
            res = supabase.table("otp_tokens").select("id").eq("email", email).eq("otp_code", str(otp_input).strip()).eq("used", 0).gt("expires_at", now).execute()
            if res.data:
                supabase.table("otp_tokens").update({"used": 1}).eq("id", res.data[0]["id"]).execute()
                return True
        else:
            _ensure_otp_table()
            conn = get_db_connection()
            row = conn.execute("SELECT id FROM otp_tokens WHERE email=? AND otp_code=? AND used=0 AND expires_at>?", (email, str(otp_input).strip(), now)).fetchone()
            if row:
                conn.execute("UPDATE otp_tokens SET used=1 WHERE id=?", (row["id"],))
                conn.commit(); conn.close()
                return True
            conn.close()
    except Exception as e:
        st.error(f"❌ ตรวจสอบ OTP ผิดพลาด: {e}")
    return False

def send_otp_email(to_email, otp_code):
    """Send OTP via SMTP (Gmail). Requires SMTP_USER & SMTP_PASSWORD in secrets."""
    smtp_user = st.secrets.get("SMTP_USER")
    smtp_pass = st.secrets.get("SMTP_PASSWORD")
    if not smtp_user or not smtp_pass:
        return False  # No SMTP configured - caller handles fallback
    try:
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;background:#0F172A;color:#F1F5F9;border-radius:16px;overflow:hidden;">
            <div style="background:linear-gradient(135deg,#1E3A8A,#0d1b3e);padding:2rem;text-align:center;">
                <div style="font-size:2.2rem;font-weight:900;background:linear-gradient(135deg,#fff,#FBBF24);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">🔧 FindSpares AI</div>
            </div>
            <div style="padding:2rem;text-align:center;">
                <p style="color:rgba(255,255,255,0.7);font-size:1rem;">รหัส OTP สำหรับการสมัครสมาชิก</p>
                <div style="font-size:3rem;font-weight:900;letter-spacing:0.4em;color:#FBBF24;margin:1.5rem 0;">{otp_code}</div>
                <p style="color:rgba(255,255,255,0.45);font-size:0.85rem;">รหัสนี้ใช้ได้ภายใน <strong style="color:#FBBF24;">10 นาที</strong><br>หากคุณไม่ได้ทำรายการนี้ กรุณาเพิกเฉยอีเมลฉบับนี้</p>
            </div>
            <div style="background:#1E293B;padding:1rem;text-align:center;font-size:0.75rem;color:rgba(255,255,255,0.3);">FindSpares AI - ระบบค้นหาอะไหล่ด้วย AI</div>
        </div>"""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🔧 FindSpares AI — รหัส OTP ของคุณ: {otp_code}"
        msg["From"] = f"FindSpares AI <{smtp_user}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"❌ ส่งอีเมลไม่สำเร็จ: {e}"); return False

def toggle_favorite(user_id, part_id):
    try:
        if USE_SUPABASE:
            check = supabase.table("favorites").select("id").eq("user_id", user_id).eq("part_id", part_id).execute()
            if check.data:
                supabase.table("favorites").delete().eq("user_id", user_id).eq("part_id", part_id).execute()
                st.toast("🗑️ ลบจากรายการโปรดแล้ว")
            else:
                supabase.table("favorites").insert({"user_id": user_id, "part_id": part_id}).execute()
                st.toast("⭐ บันทึกเป็นรายการโปรดแล้ว")
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, part_id INTEGER, UNIQUE(user_id, part_id))")
            cursor.execute("SELECT id FROM favorites WHERE user_id = ? AND part_id = ?", (user_id, part_id))
            if cursor.fetchone():
                cursor.execute("DELETE FROM favorites WHERE user_id = ? AND part_id = ?", (user_id, part_id))
                st.toast("🗑️ ลบจากรายการโปรดแล้ว")
            else:
                cursor.execute("INSERT INTO favorites (user_id, part_id) VALUES (?, ?)", (user_id, part_id))
                st.toast("⭐ บันทึกเป็นรายการโปรดแล้ว")
            conn.commit(); conn.close()
        return True
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดในระบบฐานข้อมูล: {e}")
        return False

def get_user_favorites(user_id):
    try:
        if USE_SUPABASE:
            res = supabase.table("favorites").select("part_id").eq("user_id", user_id).execute()
            return [r["part_id"] for r in res.data]
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, part_id INTEGER, UNIQUE(user_id, part_id))")
            cursor.execute("SELECT part_id FROM favorites WHERE user_id = ?", (user_id,))
            rows = cursor.fetchall(); conn.close()
            return [r["part_id"] for r in rows]
    except:
        return []

# ---------------------------
# COMMUNITY DB FUNCTIONS
# ---------------------------
def _ensure_community_tables():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS community_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            image TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS community_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit(); conn.close()

def get_community_posts():
    try:
        if USE_SUPABASE:
            res = supabase.table("community_posts").select("*, users(username)").order("created_at", desc=True).execute()
            return res.data
        else:
            _ensure_community_tables()
            conn = get_db_connection()
            rows = conn.execute("SELECT p.*, u.username FROM community_posts p JOIN users u ON p.user_id = u.id ORDER BY p.created_at DESC").fetchall()
            conn.close()
            return [dict(r) for r in rows]
    except Exception as e:
        st.error(f"❌ Error loading posts: {e}"); return []

def create_community_post(user_id, title, content, image_filename=None):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        if USE_SUPABASE:
            supabase.table("community_posts").insert({"user_id": user_id, "title": title, "content": content, "image": image_filename, "created_at": now}).execute()
        else:
            _ensure_community_tables()
            conn = get_db_connection()
            conn.execute("INSERT INTO community_posts (user_id, title, content, image, created_at) VALUES (?, ?, ?, ?, ?)", (user_id, title, content, image_filename, now))
            conn.commit(); conn.close()
        return True
    except Exception as e:
        st.error(f"❌ Error creating post: {e}"); return False

def get_community_comments(post_id):
    try:
        if USE_SUPABASE:
            res = supabase.table("community_comments").select("*, users(username)").eq("post_id", post_id).order("created_at", desc=False).execute()
            return res.data
        else:
            _ensure_community_tables()
            conn = get_db_connection()
            rows = conn.execute("SELECT c.*, u.username FROM community_comments c JOIN users u ON c.user_id = u.id WHERE c.post_id = ? ORDER BY c.created_at ASC", (post_id,)).fetchall()
            conn.close()
            return [dict(r) for r in rows]
    except Exception as e:
        return []

def create_community_comment(post_id, user_id, content):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        if USE_SUPABASE:
            supabase.table("community_comments").insert({"post_id": post_id, "user_id": user_id, "content": content, "created_at": now}).execute()
        else:
            _ensure_community_tables()
            conn = get_db_connection()
            conn.execute("INSERT INTO community_comments (post_id, user_id, content, created_at) VALUES (?, ?, ?, ?)", (post_id, user_id, content, now))
            conn.commit(); conn.close()
        return True
    except Exception as e:
        st.error(f"❌ Error creating comment: {e}"); return False

# ---------------------------
# SHOP DB FUNCTIONS
# ---------------------------
def _ensure_shop_tables():
    conn = get_db_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS shops (
        id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL UNIQUE,
        shop_name TEXT NOT NULL, address TEXT NOT NULL, latitude REAL NOT NULL,
        longitude REAL NOT NULL, open_hours TEXT, google_map_link TEXT, created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS shop_parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id INTEGER NOT NULL,
        part_name TEXT NOT NULL, car_model TEXT, brand TEXT, condition TEXT DEFAULT 'ใหม่',
        stock INTEGER DEFAULT 1, image TEXT, created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS part_embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, part_id INTEGER NOT NULL UNIQUE,
        embedding TEXT NOT NULL)""")
    conn.commit(); conn.close()

def get_user_shop(user_id):
    try:
        if USE_SUPABASE:
            res = supabase.table("shops").select("*").eq("owner_id", user_id).execute()
            return res.data[0] if res.data else None
        else:
            _ensure_shop_tables()
            conn = get_db_connection()
            row = conn.execute("SELECT * FROM shops WHERE owner_id=?", (user_id,)).fetchone()
            conn.close()
            return dict(row) if row else None
    except Exception as e:
        st.error(f"❌ {e}"); return None

def create_shop(owner_id, shop_name, address, lat, lng, open_hours):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    map_link = f"https://www.google.com/maps?q={lat},{lng}"
    try:
        if USE_SUPABASE:
            supabase.table("shops").insert({"owner_id": owner_id, "shop_name": shop_name, "address": address,
                "latitude": lat, "longitude": lng, "open_hours": open_hours, "google_map_link": map_link, "created_at": now}).execute()
        else:
            _ensure_shop_tables()
            conn = get_db_connection()
            conn.execute("INSERT INTO shops (owner_id,shop_name,address,latitude,longitude,open_hours,google_map_link,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (owner_id, shop_name, address, lat, lng, open_hours, map_link, now))
            conn.commit(); conn.close()
        return True
    except Exception as e:
        st.error(f"❌ สร้างร้านไม่สำเร็จ: {e}"); return False

def update_shop(owner_id, shop_name, address, lat, lng, open_hours):
    map_link = f"https://www.google.com/maps?q={lat},{lng}"
    try:
        if USE_SUPABASE:
            supabase.table("shops").update({"shop_name": shop_name, "address": address, "latitude": lat,
                "longitude": lng, "open_hours": open_hours, "google_map_link": map_link}).eq("owner_id", owner_id).execute()
        else:
            conn = get_db_connection()
            conn.execute("UPDATE shops SET shop_name=?,address=?,latitude=?,longitude=?,open_hours=?,google_map_link=? WHERE owner_id=?",
                (shop_name, address, lat, lng, open_hours, map_link, owner_id))
            conn.commit(); conn.close()
        return True
    except Exception as e:
        st.error(f"❌ {e}"); return False

def get_shop_products(shop_id):
    try:
        if USE_SUPABASE:
            res = supabase.table("shop_parts").select("*").eq("shop_id", shop_id).execute()
            return res.data
        else:
            _ensure_shop_tables()
            conn = get_db_connection()
            rows = conn.execute("SELECT * FROM shop_parts WHERE shop_id=? ORDER BY created_at DESC", (shop_id,)).fetchall()
            conn.close()
            return [dict(r) for r in rows]
    except: return []

def add_shop_product(shop_id, part_name, car_model, brand, condition, stock, image_filename, model, preprocess, device):
    """Add product and generate CLIP text embedding automatically."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        if USE_SUPABASE:
            res = supabase.table("shop_parts").insert({"shop_id": shop_id, "part_name": part_name, "car_model": car_model,
                "brand": brand, "condition": condition, "stock": stock, "image": image_filename, "created_at": now}).execute()
            part_id = res.data[0]["id"]
        else:
            _ensure_shop_tables()
            conn = get_db_connection()
            cur = conn.execute("INSERT INTO shop_parts (shop_id,part_name,car_model,brand,condition,stock,image,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (shop_id, part_name, car_model, brand, condition, stock, image_filename, now))
            part_id = cur.lastrowid
            conn.commit(); conn.close()

        # Auto-generate CLIP embedding from part name
        text_query = f"{part_name} {car_model or ''} {brand or ''}".strip()
        tokens = clip.tokenize([text_query], truncate=True).to(device)
        with torch.no_grad():
            vec = model.encode_text(tokens)
        vec = vec / vec.norm(dim=-1, keepdim=True)
        vec_list = vec.cpu().numpy().astype("float32")[0].tolist()
        emb_json = json.dumps(vec_list)

        if USE_SUPABASE:
            supabase.table("part_embeddings").insert({"part_id": part_id, "embedding": vec_list}).execute()
        else:
            conn = get_db_connection()
            conn.execute("INSERT OR REPLACE INTO part_embeddings (part_id, embedding) VALUES (?,?)", (part_id, emb_json))
            conn.commit(); conn.close()

        st.cache_resource.clear()  # Clear cache so new item appears in search
        return True
    except Exception as e:
        st.error(f"❌ เพิ่มสินค้าไม่สำเร็จ: {e}"); return False

def delete_shop_product(part_id):
    try:
        if USE_SUPABASE:
            supabase.table("part_embeddings").delete().eq("part_id", part_id).execute()
            supabase.table("shop_parts").delete().eq("id", part_id).execute()
        else:
            conn = get_db_connection()
            conn.execute("DELETE FROM part_embeddings WHERE part_id=?", (part_id,))
            conn.execute("DELETE FROM shop_parts WHERE id=?", (part_id,))
            conn.commit(); conn.close()
        st.cache_resource.clear()
        return True
    except Exception as e:
        st.error(f"❌ {e}"); return False

# ---------------------------
# UI CUSTOMIZATION (SIDEBAR)
# ---------------------------
with st.sidebar:
    st.title("FindSpares AI")
    if st.session_state.authenticated:
        st.success(f"👤 สวัสดีคุณ {st.session_state.username}")
        if st.button("🚪 Logout"):
            st.session_state.authenticated = False
            st.session_state.username = None
            st.session_state.user_id = None
            st.rerun()
    
    st.title("Settings")
    theme_mode = st.toggle("🌙 Night Mode", value=True)
    
    st.divider()
    st.header("🎯 ตัวกรองการค้นหา")
    max_dist = st.slider("📏 ระยะทางสูงสุด (กม.)", 0, 100, 50)
    min_match = st.slider("🤖 ความแม่นยำ AI (%)", 0, 100, 40)
    st.session_state.max_dist = max_dist
    st.session_state.min_match = min_match / 100

    st.divider()
    with st.expander("🛠️ Developer Tools (Debug DB)"):
        st.write("ตรวจสอบข้อมูลในฐานข้อมูล")
        db_tables = ["users", "favorites", "shops", "shop_parts", "part_embeddings"]
        selected_table = st.selectbox("เลือกตารางเพื่อดูข้อมูล", db_tables)
        if st.button("👁️ ดึงข้อมูลตาราง", use_container_width=True):
            try:
                if USE_SUPABASE:
                    res = supabase.table(selected_table).select("*").limit(100).execute()
                    st.dataframe(res.data)
                else:
                    conn = get_db_connection()
                    st.dataframe(conn.execute(f"SELECT * FROM {selected_table} LIMIT 100").fetchall())
                    conn.close()
            except Exception as e:
                st.error(f"⚠️ ไม่สามารถเรียกดูข้อมูลได้: {e}")
    
    st.divider()
    st.markdown("FindSpares AI matches your requirements with local shop data using CLIP models.")

theme_css = f"""
<style>
@media (max-width: 640px) {{
    .main .block-container {{ padding: 1rem !important; }}
    h1 {{ font-size: 1.8rem !important; }}
}}
.stCard {{
    border-radius: 12px; padding: 15px; margin-bottom: 20px;
    border: 1px solid #1E3A8A; transition: transform 0.2s;
    background-color: rgba(30, 58, 138, 0.05);
}}
.stCard:hover {{
    transform: translateY(-5px); box-shadow: 0 4px 15px rgba(251, 191, 36, 0.3);
}}
/* Custom Button Style */
div.stButton > button {{
    background-color: #1E3A8A !important; color: #FBBF24 !important;
    border: 1px solid #FBBF24 !important; border-radius: 8px !important;
}}
div.stButton > button:hover {{
    background-color: #FBBF24 !important; color: #1E3A8A !important;
}}
div.stLinkButton > a {{
    background-color: #FBBF24 !important; color: #1E3A8A !important;
    border-radius: 8px !important; font-weight: bold !important;
}}
</style>
"""
if theme_mode:
    theme_css += """
<style>
.stApp { background-color: #0F172A; color: #F1F5F9; }
[data-testid="stHeader"] { background-color: rgba(15, 23, 42, 0.9); }
h1, h2, h3, p, span, label { color: #F1F5F9 !important; }
.stTextInput input, .stFileUploader section { background-color: #1E293B !important; color: white !important; border: 1px solid #1E3A8A !important; }
.stProgress > div > div > div > div { background-color: #FBBF24 !important; }
</style>
"""
else:
    theme_css += """
<style>
.stApp { background-color: #F8FAFC; }
[data-testid="stMain"] h1, [data-testid="stMain"] h2, [data-testid="stMain"] h3, 
[data-testid="stMain"] p, [data-testid="stMain"] span, [data-testid="stMain"] label, 
[data-testid="stMain"] div, [data-testid="stMain"] .stMarkdown, 
[data-testid="stMain"] button[data-baseweb="tab"] p { 
    color: #1E293B !important; 
}
[data-testid="stMain"] div.stButton > button, 
[data-testid="stMain"] div.stLinkButton > a { 
    color: #FBBF24 !important; 
}
/* Full-screen Dialog for Mobile (Google Lens style) */
@media (max-width: 640px) {
    div[data-testid="stDialog"] div[role="dialog"] {
        width: 100vw !important; height: 100vh !important;
        min-width: 100vw !important; min-height: 100vh !important;
        margin: 0 !important; padding: 0 !important;
        position: fixed !important; top: 0 !important; left: 0 !important; border-radius: 0 !important;
    }
    div[data-testid="stDialog"] [data-testid="stVerticalBlock"] { padding: 0 !important; }
}
.stProgress > div > div > div > div { background-color: #1E3A8A !important; }
</style>
"""
st.markdown(theme_css, unsafe_allow_html=True)

# ---------------------------
# SCREENS
# ---------------------------
def render_auth():
    st.markdown("<h1 style='text-align: center;'>🔐 ยินดีต้อนรับสู่ FindSpares AI</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        tab_login, tab_reg = st.tabs(["🔑 เข้าสู่ระบบ", "📝 ลงทะเบียน (Email OTP)"])

        # ─── LOGIN TAB ───────────────────────────────────────
        with tab_login:
            with st.form("login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("เข้าสู่ระบบ", use_container_width=True):
                    uid = verify_user(u, p)
                    if uid:
                        st.session_state.authenticated = True
                        st.session_state.username = u
                        st.session_state.user_id = uid
                        st.rerun()
                    else:
                        st.error("❌ Username หรือ Password ไม่ถูกต้อง")

        # ─── REGISTER TAB (2-Step OTP) ────────────────────────
        with tab_reg:
            has_smtp = bool(st.secrets.get("SMTP_USER") and st.secrets.get("SMTP_PASSWORD"))
            if not has_smtp:
                st.info("💡 **โหมดทดสอบ:** ยังไม่ได้ตั้งค่า SMTP — รหัส OTP จะแสดงในหน้าจอแทนการส่งอีเมลจริง")

            # ── Step 1: กรอกข้อมูล ──
            if st.session_state.reg_step == 1:
                st.caption("ขั้นตอนที่ 1/2 — กรอกข้อมูลสมาชิก")
                with st.form("reg_form"):
                    r_user  = st.text_input("Username", placeholder="ชื่อผู้ใช้งาน")
                    r_email = st.text_input("Email", placeholder="yourname@gmail.com")
                    r_pw    = st.text_input("Password", type="password", placeholder="อย่างน้อย 6 ตัวอักษร")
                    r_pw2   = st.text_input("ยืนยัน Password", type="password")
                    send_btn = st.form_submit_button("📩 ส่งรหัส OTP ไปยังอีเมล", use_container_width=True)

                if send_btn:
                    if not all([r_user, r_email, r_pw, r_pw2]):
                        st.warning("⚠️ กรุณากรอกข้อมูลให้ครบทุกช่อง")
                    elif r_pw != r_pw2:
                        st.error("❌ รหัสผ่านไม่ตรงกัน")
                    elif len(r_pw) < 6:
                        st.warning("⚠️ รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร")
                    else:
                        otp_code = str(random.randint(100000, 999999))
                        if save_otp(r_email, otp_code):
                            if has_smtp:
                                sent = send_otp_email(r_email, otp_code)
                                if not sent:
                                    st.error("❌ ส่งอีเมลไม่สำเร็จ — กรุณาตรวจสอบการตั้งค่า SMTP")
                                    st.stop()
                            
                            st.session_state.reg_pending = {
                                "username": r_user, 
                                "email": r_email, 
                                "password": r_pw,
                                "test_otp": otp_code if not has_smtp else None
                            }
                            st.session_state.reg_step = 2
                            st.rerun()

            # ── Step 2: ยืนยัน OTP ──
            elif st.session_state.reg_step == 2:
                pending = st.session_state.reg_pending
                st.caption("ขั้นตอนที่ 2/2 — ยืนยัน OTP")
                st.info(f"✉️ ส่งรหัส OTP 6 หลักไปที่: **{pending.get('email', '')}**")
                
                if not has_smtp and pending.get("test_otp"):
                    st.success(f"🔑 **[โหมดทดสอบ] รหัส OTP ของคุณคือ:** `{pending['test_otp']}`")
                
                otp_input = st.text_input("กรอกรหัส OTP", max_chars=6, placeholder="123456")

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ ยืนยัน OTP & สมัครสมาชิก", use_container_width=True, type="primary"):
                        if len(otp_input.strip()) != 6:
                            st.warning("⚠️ กรุณากรอกรหัส 6 หลักให้ครบ")
                        elif verify_otp(pending["email"], otp_input):
                            ok = add_user(pending["username"], pending["email"], pending["password"])
                            if ok:
                                st.success("🎉 สมัครสมาชิกสำเร็จ! กรุณาเข้าสู่ระบบ")
                                st.session_state.reg_step = 1
                                st.session_state.reg_pending = {}
                                st.rerun()
                        else:
                            st.error("❌ รหัส OTP ไม่ถูกต้อง หรือหมดอายุแล้ว")
                with c2:
                    if st.button("← แก้ไขข้อมูล", use_container_width=True):
                        st.session_state.reg_step = 1
                        st.rerun()

def render_main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    @st.cache_resource
    def load_clip_model():
        model, preprocess = clip.load("ViT-B/32", device=device)
        return model, preprocess
    model, preprocess = load_clip_model()

    @st.cache_resource
    def load_vectors_cached():
        if USE_SUPABASE:
            res = supabase.table("part_embeddings").select("*, shop_parts(*, shops(*))").execute()
            data = res.data
            if not data: return None, []
            vectors, items = [], []
            for d in data:
                try:
                    sp = d["shop_parts"]; s = sp["shops"]
                    item_dict = {
                        "id": sp["id"], "part_name": sp["part_name"], "image": sp["image"],
                        "shop_name": s["shop_name"], "latitude": s["latitude"], 
                        "longitude": s["longitude"], "google_map_link": s["google_map_link"]
                    }
                    vec = np.array(d["embedding"]).astype("float32")
                    vec = vec / np.linalg.norm(vec)
                    vectors.append(vec); items.append(item_dict)
                except: continue
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT sp.id, sp.part_name, sp.image, s.shop_name, s.latitude, s.longitude, s.google_map_link, pe.embedding FROM part_embeddings pe JOIN shop_parts sp ON pe.part_id=sp.id JOIN shops s ON sp.shop_id=s.id")
            rows = cursor.fetchall(); conn.close()
            if not rows: return None, []
            vectors, items = [], []
            for d in rows:
                item_dict = dict(d)
                vec = np.array(json.loads(item_dict["embedding"])).astype("float32")
                vec = vec / np.linalg.norm(vec)
                vectors.append(vec); items.append(item_dict)
        if not vectors: return None, []
        vectors = np.array(vectors)
        idx = faiss.IndexFlatIP(vectors.shape[1]); idx.add(vectors)
        return idx, items

    with st.spinner("📦 กำลังโหลดข้อมูล..."):
        idx, items = load_vectors_cached()

    if idx is None:
        st.warning("⚠️ ฐานข้อมูลว่างเปล่า กรุณาเพิ่มข้อมูลอะไหล่ใน Supabase/SQLite ก่อนใช้งานครับ")
        if st.button("🔄 โหลดข้อมูลใหม่ (Refresh Cache)", use_container_width=True):
            st.cache_resource.clear()
            st.rerun()

    def encode_text(text):
        tokens = clip.tokenize([text], truncate=True).to(device)
        with torch.no_grad(): vec = model.encode_text(tokens)
        vec = vec / vec.norm(dim=-1, keepdim=True)
        return vec.cpu().numpy().astype("float32")

    def encode_image(img):
        proc = preprocess(img).unsqueeze(0).to(device)
        with torch.no_grad(): vec = model.encode_image(proc)
        vec = vec / vec.norm(dim=-1, keepdim=True)
        return vec.cpu().numpy().astype("float32")

    def search_parts(q_vec, lat, lng, q_text=None):
        if idx is None: return []
        D, I = idx.search(q_vec, min(200, len(items)))
        results, seen = [], set()

        # Expand Keywords for Smart Filtering
        search_terms = []
        if q_text:
            q_low = q_text.lower()
            search_terms.append(q_low)
            for category, syns in SYNONYM_MAP.items():
                if q_low == category.lower() or any(s.lower() in q_low for s in syns):
                    search_terms.extend([s.lower() for s in syns])
            search_terms = list(set(search_terms))

        for score, i in zip(D[0], I[0]):
            if i == -1: continue
            item = items[i]
            if item["id"] in seen: continue
            
            # Smart Filter
            if search_terms:
                name_low = item["part_name"].lower()
                if not any(term in name_low for term in search_terms): 
                    continue

            seen.add(item["id"])
            R = 6371
            dlat, dlon = math.radians(item["latitude"]-lat), math.radians(item["longitude"]-lng)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(item["latitude"])) * math.sin(dlon/2)**2
            dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            results.append({
                "id": item["id"], "part_name": item["part_name"], "image": item["image"], "shop_name": item["shop_name"],
                "distance": dist, "score": float(max(0, min(1, score))), "map": item["google_map_link"]
            })
        return results

    st.title("🔧 FindSpares AI Search")
    tab_search, tab_fav, tab_community, tab_shop = st.tabs(["🔍 ค้นหาอะไหล่", "⭐ รายการโปรด", "💬 ชุมชนคนรักรถ", "🏪 ร้านค้าของฉัน"])
    
    @st.dialog("📸 FindSpares Scanner", width="large")
    def camera_modal():
        c_img = st.camera_input("แสกนอะไหล่", label_visibility="collapsed")
        if c_img:
            with st.spinner("🔎 Searching..."):
                img = Image.open(c_img).convert("RGB")
                vec = encode_image(img)
                res = search_parts(vec, 13.2839, 100.9289)
                st.session_state.results = sorted(res, key=lambda x: (-x["score"], x["distance"]))
                st.session_state.page = 1
                st.rerun()

    with tab_search:
        st.info("📍 ค้นหาด้วยชื่อ หรือ อัปโหลด/ถ่ายรูป")
        scol, ccol = st.columns([7, 1])
        with scol:
            q = st.text_input("🔍 พิมพ์ชื่ออะไหล่ หรือ อัปโหลดรูป", key="search_q", label_visibility="collapsed")
        with ccol:
            if st.button("📸", key="btn_cam_modal", help="เปิดกล้องแสกนอะไหล่"):
                camera_modal()
        up = st.file_uploader("📁 อัปโหลดรูปภาพ", type=["jpg","png","jpeg"], label_visibility="collapsed")
        
        if q or up:
            with st.spinner("🔎 กำลังประมวลผล..."):
                if up:
                    img = Image.open(up).convert("RGB"); vec = encode_image(img)
                    res = search_parts(vec, 13.2839, 100.9289)
                elif q:
                    res = search_parts(encode_text(q), 13.2839, 100.9289, q)
                if 'res' in locals():
                    st.session_state.results = sorted(res, key=lambda x: (-x["score"], x["distance"]))
                    st.session_state.page = 1

        if st.session_state.get("results"):
            max_d = st.session_state.get("max_dist", 50); min_m = st.session_state.get("min_match", 0.4)
            filtered_res = [r for r in st.session_state.results if r["distance"] <= max_d and r["score"] >= min_m]
            if filtered_res: render_grid(filtered_res)
            else: st.warning(f"🔎 ไม่พบอะไหล่ภายในระยะ {max_d} กม. หรือ Match > {int(min_m*100)}%")

    with tab_fav:
        fav_ids = get_user_favorites(st.session_state.user_id)
        if not fav_ids: st.info("คุณยังไม่มีรายการโปรด")
        else:
            fav_items = [item for item in items if item["id"] in fav_ids]
            res = []
            for item in fav_items:
                res.append({"id": item["id"], "part_name": item["part_name"], "image": item["image"], "shop_name": item["shop_name"], "distance": 0, "score": 1.0, "map": item["google_map_link"]})
            render_grid(res, is_fav_view=True)

    with tab_community:
        st.header("💬 ชุมชนคนรักรถ (Community)")
        
        # New Post Section
        with st.expander("➕ ตั้งกระทู้ใหม่"):
            with st.form("new_post"):
                p_title = st.text_input("หัวข้อกระทู้", placeholder="เช่น อะไหล่ชิ้นนี้คืออะไรครับ?")
                p_content = st.text_area("เนื้อหา", placeholder="สอบถาม หรือ แบ่งปันข้อมูล...")
                p_img = st.file_uploader("แนบรูปภาพ (ถ้ามี)", type=["jpg", "png", "jpeg"])
                if st.form_submit_button("📤 โพสต์", type="primary"):
                    if p_title.strip() and p_content.strip():
                        img_filename = None
                        if p_img:
                            os.makedirs("shop_parts", exist_ok=True)
                            img_filename = f"post_{datetime.utcnow().timestamp()}.jpg"
                            img_path = os.path.join("shop_parts", img_filename)
                            with open(img_path, "wb") as f: f.write(p_img.getbuffer())
                        if create_community_post(st.session_state.user_id, p_title, p_content, img_filename):
                            st.success("✅ โพสต์สำเร็จ!")
                            st.rerun()
                    else:
                        st.warning("⚠️ กรุณากรอกหัวข้อและเนื้อหา")

        st.divider()
        st.subheader("📰 กระทู้ล่าสุด")
        posts = get_community_posts()
        if not posts:
            st.info("ยังไม่มีกระทู้ในขณะนี้ เป็นคนแรกที่ตั้งกระทู้สิ!")
        else:
            for post in posts:
                with st.container(border=True):
                    pc1, pc2 = st.columns([1, 5])
                    with pc1:
                        st.markdown(f"**👤 {post['username']}**")
                        st.caption(f"🕒 {post['created_at']}")
                    with pc2:
                        st.markdown(f"### {post['title']}")
                        st.write(post['content'])
                        if post.get('image'):
                            img_p = f"shop_parts/{post['image']}"
                            if os.path.exists(img_p): st.image(img_p, width=300)
                    
                    with st.expander("💬 ดูความคิดเห็น / ตอบกลับ"):
                        comments = get_community_comments(post["id"])
                        if comments:
                            for c in comments:
                                st.markdown(f"**{c['username']}**: {c['content']} *(<small>{c['created_at']}</small>)*", unsafe_allow_html=True)
                        else:
                            st.caption("ยังไม่มีความคิดเห็น")
                        
                        # Add comment form
                        c_text = st.text_input(f"แสดงความคิดเห็น", key=f"c_in_{post['id']}")
                        if st.button("ส่งความคิดเห็น", key=f"c_btn_{post['id']}"):
                            if c_text.strip():
                                if create_community_comment(post["id"], st.session_state.user_id, c_text):
                                    st.rerun()

    with tab_shop:
        st.header("🏪 ร้านค้าของฉัน")
        my_shop = get_user_shop(st.session_state.user_id)

        # ── Create / Edit Shop ──
        with st.expander("⚙️ ข้อมูลร้านค้า", expanded=(my_shop is None)):
            if my_shop is None:
                st.info("📍 กรุณาสร้างร้านค้าของคุณก่อนเพิ่มสินค้า")
            with st.form("shop_form"):
                s_name = st.text_input("ชื่อร้าน*", value=my_shop["shop_name"] if my_shop else "")
                s_addr = st.text_area("ที่อยู่ร้าน*", value=my_shop["address"] if my_shop else "")
                sc1, sc2 = st.columns(2)
                with sc1: s_lat = st.number_input("ละติจูด (Latitude)*", value=float(my_shop["latitude"]) if my_shop else 13.7563, format="%.6f", help="ดูใน Google Maps > คลิกสังเขตร้าน > คัดลอก Lat,Lng")
                with sc2: s_lng = st.number_input("ลองจิจูด (Longitude)*", value=float(my_shop["longitude"]) if my_shop else 100.5018, format="%.6f")
                s_hours = st.text_input("เวลาเปิด-ปิด", value=my_shop["open_hours"] if my_shop else "", placeholder="เช่น จ-ส 8:00-18:00")
                submit_label = "✅ บันทึกการเปลี่ยนแปลง" if my_shop else "🏪 สร้างร้านค้า"
                if st.form_submit_button(submit_label, use_container_width=True, type="primary"):
                    if not s_name.strip() or not s_addr.strip():
                        st.warning("⚠️ กรุณากรอกชื่อร้านและที่อยู่")
                    else:
                        ok = update_shop(st.session_state.user_id, s_name, s_addr, s_lat, s_lng, s_hours) if my_shop else create_shop(st.session_state.user_id, s_name, s_addr, s_lat, s_lng, s_hours)
                        if ok: st.success("✅ สำเร็จ!"); st.rerun()

        # ── Products List ──
        if my_shop:
            st.subheader(f"🏪 {my_shop['shop_name']}")
            st.caption(f"📍 {my_shop['address']} | 🕒 {my_shop.get('open_hours','N/A')}")
            st.divider()

            # Add Product Form
            with st.expander("➕ เพิ่มสินค้าใหม่"):
                with st.form("add_product"):
                    p1, p2 = st.columns(2)
                    with p1:
                        pn = st.text_input("ชื่อสินค้า*", placeholder="เช่น Brake Pad")
                        pb = st.text_input("ยี่ห้อรถ (ถ้ามี)", placeholder="เช่น Toyota, Honda")
                    with p2:
                        pm = st.text_input("รุ่นรถ (ถ้ามี)", placeholder="เช่น Camry 2020")
                        ps = st.number_input("จำนวนสต็อก*", min_value=1, value=1)
                    pc = st.selectbox("สภาพสินค้า", ["ใหม่", "มือสอง", "OEM", "เกรด A"])
                    pi = st.file_uploader("รูปสินค้า*", type=["jpg","png","jpeg"])
                    if st.form_submit_button("➕ เพิ่มสินค้า", type="primary"):
                        if not pn.strip() or not pi:
                            st.warning("⚠️ กรุณากรอกชื่อสินค้าและแนบรูป")
                        else:
                            os.makedirs("shop_parts", exist_ok=True)
                            img_fn = f"prod_{my_shop['id']}_{datetime.utcnow().timestamp()}.jpg"
                            with open(os.path.join("shop_parts", img_fn), "wb") as f: f.write(pi.getbuffer())
                            with st.spinner("🤖 กำลังสร้าง AI Embedding..."):
                                ok = add_shop_product(my_shop["id"], pn, pm, pb, pc, ps, img_fn, model, preprocess, device)
                            if ok: st.success("✅ เพิ่มสินค้าและอัปเดต AI Search สำเร็จ!"); st.rerun()

            # Products Grid
            products = get_shop_products(my_shop["id"])
            st.subheader(f"📦 สินค้าทั้งหมด ({len(products)} รายการ)")
            if not products:
                st.info("ยังไม่มีสินค้า กดปุ่มเพิ่มสินค้าด้านบนได้เลย!")
            else:
                gcols = st.columns(3)
                for gi, prod in enumerate(products):
                    with gcols[gi % 3]:
                        with st.container(border=True):
                            img_p = f"shop_parts/{prod['image']}" if prod.get("image") else None
                            if img_p and os.path.exists(img_p): st.image(img_p, use_container_width=True)
                            else: st.image("https://via.placeholder.com/300x200?text=No+Image", use_container_width=True)
                            st.markdown(f"**{prod['part_name']}**")
                            if prod.get("car_model"): st.caption(f"🚗 {prod['car_model']}")
                            if prod.get("brand"): st.caption(f"🏷️ {prod['brand']}")
                            st.caption(f"✅ {prod['condition']} | 📦 คงเหลือ {prod['stock']} ชิ้น")
                            if st.button("🗑️ ลบสินค้า", key=f"del_{prod['id']}", use_container_width=True):
                                if delete_shop_product(prod["id"]): st.rerun()

def render_grid(results, is_fav_view=False):
    per_page = 9; total_p = math.ceil(len(results)/per_page); page = st.session_state.get("page", 1)
    page_res = results[(page-1)*per_page : page*per_page]
    fav_ids = get_user_favorites(st.session_state.user_id)
    cols = st.columns(3)
    for i, r in enumerate(page_res):
        with cols[i % 3]:
            with st.container(border=True):
                path = f"shop_parts/{r['image']}"
                if os.path.exists(path): st.image(path, use_container_width=True)
                else: st.image("https://via.placeholder.com/300x200?text=No+Image", use_container_width=True)
                h1, h2 = st.columns([4, 1])
                with h1: st.subheader(r['part_name'])
                with h2:
                    star_icon = "⭐" if r["id"] in fav_ids else "☆"
                    if st.button(star_icon, key=f"fav_{r['id']}_{'v' if is_fav_view else 's'}"):
                        toggle_favorite(st.session_state.user_id, r["id"]); st.rerun()
                st.write(f"🏪 {r['shop_name']}")
                if not is_fav_view:
                    st.write(f"📍 {r['distance']:.2f} กม.")
                    st.progress(r["score"], text=f"Match: {int(r['score']*100)}%")
                st.link_button("🗺️ แผนที่", r['map'], use_container_width=True)
    if total_p > 1:
        pc1, pc2, pc3 = st.columns([1, 2, 1])
        with pc1:
            if st.button("⬅️ ก่อนหน้า", key="prev") and page > 1: st.session_state.page -= 1; st.rerun()
        with pc2: st.write(f"หน้า {page}/{total_p}")
        with pc3:
            if st.button("ถัดไป ➡️", key="next") and page < total_p: st.session_state.page += 1; st.rerun()

def render_landing():
    # Hide sidebar on landing page
    st.markdown("""
    <style>
        [data-testid="stSidebar"] { display: none; }
        .landing-container {
            display: flex; flex-direction: column; 
            align-items: center; justify-content: center;
            height: 70vh; text-align: center;
        }
        .landing-title {
            font-size: 5rem; font-weight: 900;
            background: linear-gradient(135deg, #1E3A8A 0%, #FBBF24 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }
        .landing-subtitle {
            font-size: 1.5rem; color: #64748B; margin-bottom: 3rem;
        }
    </style>
    <div class="landing-container">
        <div class="landing-title">FindSpares AI</div>
        <div class="landing-subtitle">ระบบค้นหาชิ้นส่วนอะไหล่ด้วย AI อัจฉริยะ</div>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("🚀 เริ่มต้นใช้งาน", use_container_width=True, type="primary"):
            st.session_state.has_started = True
            st.rerun()

if not st.session_state.has_started:
    render_landing()
elif not st.session_state.authenticated: 
    render_auth()
else: 
    render_main()
