# SPDX-License-Identifier: GPL-3.0-or-later
import imaplib
import email
from email.header import decode_header
import os
import re
import json
import time
import base64
import requests
from bs4 import BeautifulSoup
from typing import Optional

# 环境变量获取
USERNAME = os.getenv('EUSERV_USERNAME')
PASSWORD = os.getenv('EUSERV_PASSWORD')
TRUECAPTCHA_USERID = os.getenv('TRUECAPTCHA_USERID')
TRUECAPTCHA_APIKEY = os.getenv('TRUECAPTCHA_APIKEY')
IMAP_SERVER = os.getenv('IMAP_SERVER')
MAIL_ADDRESS = os.getenv('MAIL_ADDRESS')
APP_PASSWORD = os.getenv('APP_PASSWORD')
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_USER_ID = os.getenv('TG_USER_ID')

COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
}

desp = ""

def log(info: str):
    print(info)
    global desp
    desp += info + "\n\n"

def save_debug_page(content, filename="login_error.html"):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    log(f"⚠️ 已保存调试页面: {filename}")

def captcha_solver(captcha_image_url: str, session: requests.Session) -> str:
    try:
        response = session.get(captcha_image_url, timeout=15)
        encoded_string = base64.b64encode(response.content).decode('utf-8')
        url = "https://api.apitruecaptcha.org/one/gettext"
        data = {"userid": TRUECAPTCHA_USERID, "apikey": TRUECAPTCHA_APIKEY, "data": encoded_string}
        r = requests.post(url=url, json=data, timeout=20).json()
        return r.get("result", "").replace(" ", "")
    except Exception as e:
        log(f"验证码识别异常: {e}")
        return ""

def login(username, password):
    url = "https://support.euserv.com/index.iphp"
    captcha_image_url = "https://support.euserv.com/securimage_show.php"
    session = requests.Session()
    session.headers.update(COMMON_HEADERS)
    
    try:
        # 1. 获取登录页，提取 HTML 里的 sess_id
        r1 = session.get(url, timeout=20)
        # 根据你提供的源码精准匹配 43 位左右的 sess_id
        sess_id_match = re.search(r'name="sess_id" value="([a-f0-9]{32,})"', r1.text)
        sess_id = sess_id_match.group(1) if sess_id_match else ""
        
        if not sess_id:
            log("❌ 未能在页面中找到 sess_id，请检查网络或 IP 是否被封")
            return "-1", session

        # 2. 模拟加载小 Logo（避开机器人检测）
        session.get("https://support.euserv.com/pic/logo_small.png", timeout=10)

        # 3. 提交登录表单
        login_data = {
            "email": username,
            "password": password,
            "form_selected_language": "en",
            "Submit": "Login",
            "subaction": "login",
            "sess_id": sess_id
        }
        
        session.headers.update({'Referer': url, 'Origin': 'https://support.euserv.com'})
        r2 = session.post(url, data=login_data, timeout=20)

        # 4. 如果出现验证码
        if "solve the following captcha" in r2.text:
            log("🧩 发现验证码，正在识别...")
            code = captcha_solver(captcha_image_url, session)
            log(f"🔢 验证码: {code}")
            r2 = session.post(url, data={"subaction": "login", "sess_id": sess_id, "captcha_code": code}, timeout=20)

        # 5. 结果判断
        if any(x in r2.text for x in ["Logout", "Hello", "customer-data"]):
            log("✅ 登录成功")
            return sess_id, session
        else:
            save_debug_page(r2.text, f"fail_{username[:3]}.html")
            log("❌ 登录结果验证失败，请确认账号密码是否正确")
            
    except Exception as e:
        log(f"❌ 登录异常: {e}")
        
    return "-1", session

def get_servers(sess_id, session):
    d = {}
    url = f"https://support.euserv.com/index.iphp?sess_id={sess_id}"
    try:
        f = session.get(url, timeout=20)
        soup = BeautifulSoup(f.text, "html.parser")
        for tr in soup.select("#kc2_order_customer_orders_tab_content_1 .kc2_order_table tr"):
            server_id = tr.select(".td-z1-sp1-kc")
            if not server_id: continue
            action_text = tr.select(".td-z1-sp2-kc")[0].get_text()
            can_renew = "Contract extension possible from" not in action_text
            d[server_id[0].get_text()] = can_renew
    except: pass
    return d

def get_mail_pin(imap_server, mail_address, app_password, sender_filter, subject_filter, max_mails, code_pattern, timeout):
    log(f"[Mail] 正在搜索邮件...")
    try:
        imap = imaplib.IMAP4_SSL(imap_server)
        imap.login(mail_address, app_password)
        imap.select("INBOX")
        start_time = time.time()
        while time.time() - start_time < timeout:
            _, data = imap.search(None, "ALL")
            mail_ids = data[0].split()
            # 核心改进：从最新的邮件开始查找
            for num in reversed(mail_ids[-max_mails:]):
                _, msg_data = imap.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                from_ = decode_header(msg.get("From"))[0][0]
                if isinstance(from_, bytes): from_ = from_.decode()
                if sender_filter.lower() in from_.lower() or "euserv" in from_.lower():
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode()
                    else: body = msg.get_payload(decode=True).decode()
                    match = re.search(code_pattern, body)
                    if match:
                        pin = match.group(0)
                        imap.store(num, '+FLAGS', '\\Seen')
                        imap.logout()
                        return pin
            time.sleep(5)
        imap.logout()
    except Exception as e: log(f"[Mail] 错误: {e}")
    return None

def renew(sess_id, session, password, order_id):
    url = "https://support.euserv.com/index.iphp"
    session.post(url, data={
        "Submit": "Extend contract", "sess_id": sess_id, "ord_no": order_id,
        "subaction": "choose_order", "choose_order_subaction": "show_contract_details",
    }, timeout=20)
    session.post(url, data={
        "sess_id": sess_id, "subaction": "show_kc2_security_password_dialog",
        "prefix": "kc2_customer_contract_details_extend_contract_", "type": "1",
    }, timeout=20)
    log("[Mail] PIN 邮件已触发，等待中...")
    time.sleep(12)
    pin = get_mail_pin(IMAP_SERVER, MAIL_ADDRESS, APP_PASSWORD, SENDER_FILTER, SUBJECT_FILTER, MAX_MAILS, CODE_PATTER, 60)
    if not pin: raise Exception("无法获取 PIN")
    res = session.post(url, data={
        "auth": pin, "sess_id": sess_id, "subaction": "kc2_security_password_get_token",
        "prefix": "kc2_customer_contract_details_extend_contract_", "type": 1,
        "ident": f"kc2_customer_contract_details_extend_contract_{order_id}",
    }, timeout=20)
    try:
        res_json = res.json()
        if res_json.get("rs") == "success":
            token = res_json["token"]["value"]
            session.post(url, data={
                "sess_id": sess_id, "ord_id": order_id,
                "subaction": "kc2_customer_contract_details_extend_contract_term", "token": token,
            }, timeout=20)
            return True
    except: pass
    return False

def main_handler(event, context):
    if not USERNAME or not PASSWORD: return
    user_list = USERNAME.strip().split()
    passwd_list = PASSWORD.strip().split()
    for i in range(len(user_list)):
        log(f"--- 处理账号: {user_list[i]} ---")
        sessid, s = login(user_list[i], passwd_list[i])
        if sessid == "-1": continue
        
        servers = get_servers(sessid, s)
        log(f"检测到 {len(servers)} 台服务器")
        for k, can_renew in servers.items():
            if can_renew:
                log(f"正在续期 {k}...")
                if renew(sessid, s, passwd_list[i], k): log(f"✅ {k} 续期成功")
                else: log(f"❌ {k} 续期失败")
            else: log(f"ℹ️ {k} 无需续期")
        time.sleep(5)

    if TG_BOT_TOKEN and TG_USER_ID:
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", 
                      data={"chat_id": TG_USER_ID, "text": desp, "parse_mode": "HTML"})

if __name__ == "__main__":
    main_handler(None, None)
