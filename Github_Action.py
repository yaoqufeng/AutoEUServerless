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
SENDER_FILTER = 'EUserv Support'
SUBJECT_FILTER = 'EUserv - PIN for the Confirmation of a Security Check'
MAX_MAILS = 15
CODE_PATTER = r"\b\d{6}\b"
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_USER_ID = os.getenv('TG_USER_ID')
TG_API_HOST = "https://api.telegram.org"

LOGIN_MAX_RETRY_COUNT = 5
WAITING_TIME_OF_PIN = 12
SEARCH_TIMEOUT = 60

# --- 核心改进：更真实的浏览器 Headers ---
COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0',
}

desp = ""

def log(info: str):
    emoji_map = {
        "正在续费": "🔄", "检测到": "🔍", "ServerID": "🔗", "无需更新": "✅",
        "续订错误": "⚠️", "已成功续订": "🎉", "所有工作完成": "🏁", "登陆失败": "❗",
        "验证通过": "✔️", "验证失败": "❌", "API 使用次数": "📊", "验证码是": "🔢",
        "登录尝试": "🔑", "[Mail]": "📧", "[Captcha Solver]": "🧩", "[AutoEUServerless]": "🌐",
    }
    for key, emoji in emoji_map.items():
        if key in info:
            info = emoji + " " + info
            break
    print(info)
    global desp
    desp += info + "\n\n"

def captcha_solver(captcha_image_url: str, session: requests.Session) -> dict:
    try:
        # 获取验证码图片时带上 Referer
        response = session.get(captcha_image_url, headers={'Referer': 'https://support.euserv.com/index.iphp'}, timeout=15)
        encoded_string = base64.b64encode(response.content).decode('utf-8')
        url = "https://api.apitruecaptcha.org/one/gettext"
        data = {
            "userid": TRUECAPTCHA_USERID,
            "apikey": TRUECAPTCHA_APIKEY,
            "case": "mixed",
            "mode": "human",
            "data": encoded_string,
        }
        r = requests.post(url=url, json=data, timeout=20)
        return r.json()
    except Exception as e:
        log(f"验证码请求异常: {e}")
        return {}

def handle_captcha_solved_result(solved: dict) -> str:
    if "result" in solved:
        text = solved["result"].replace(" ", "")
        if any(op in text for op in ["+", "-", "x", "*"]):
            try:
                processed_text = text.lower().replace("x", "*")
                return str(eval(re.sub(r'[^0-9*+-]', '', processed_text)))
            except: return text
        return text
    raise KeyError("未找到解析结果")

def get_captcha_solver_usage() -> dict:
    url = "https://api.apitruecaptcha.org/one/getusage"
    params = {"username": TRUECAPTCHA_USERID, "apikey": TRUECAPTCHA_APIKEY}
    try:
        r = requests.get(url=url, params=params, timeout=10)
        return r.json()
    except: return [{"date": "Error", "count": "0"}]

def login(username, password):
    url = "https://support.euserv.com/index.iphp"
    captcha_image_url = "https://support.euserv.com/securimage_show.php"
    session = requests.Session()
    session.headers.update(COMMON_HEADERS)
    
    # 第一次访问，建立 Session
    try:
        sess = session.get(url, timeout=20)
        sess_ids = re.findall("PHPSESSID=(\\w{10,100});", str(sess.headers))
        sess_id = sess_ids[0] if sess_ids else ""
        
        # 模拟登录数据
        login_data = {
            "email": username, 
            "password": password, 
            "form_selected_language": "en",
            "Submit": "Login", 
            "subaction": "login", 
            "sess_id": sess_id,
        }
        
        # 增加 Referer 模拟
        session.headers.update({'Referer': url, 'Origin': 'https://support.euserv.com'})
        f = session.post(url, data=login_data, timeout=20)
        
        # 检查是否触发验证码
        if "solve the following captcha" in f.text:
            log("[Captcha Solver] 正在进行验证码识别...")
            solved_result = captcha_solver(captcha_image_url, session)
            captcha_code = handle_captcha_solved_result(solved_result)
            log(f"[Captcha Solver] 识别出的验证码: {captcha_code}")

            f2 = session.post(url, data={
                "subaction": "login", "sess_id": sess_id, "captcha_code": captcha_code,
            }, timeout=20)
            
            if "Logout" in f2.text or "Hello" in f2.text:
                return sess_id, session
        
        if "Logout" in f.text or "Hello" in f.text:
            return sess_id, session
            
    except Exception as e:
        log(f"登录过程发生网络异常: {e}")
        
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
    log(f"[Mail] 正在搜索最新邮件...")
    try:
        imap = imaplib.IMAP4_SSL(imap_server)
        imap.login(mail_address, app_password)
        imap.select("INBOX")
        start_time = time.time()
        while time.time() - start_time < timeout:
            _, data = imap.search(None, "ALL")
            mail_ids = data[0].split()
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
    time.sleep(WAITING_TIME_OF_PIN)
    pin = get_mail_pin(IMAP_SERVER, MAIL_ADDRESS, APP_PASSWORD, SENDER_FILTER, SUBJECT_FILTER, MAX_MAILS, CODE_PATTER, SEARCH_TIMEOUT)
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
        log(f"开始处理第 {i+1} 个账号")
        success = False
        for retry in range(LOGIN_MAX_RETRY_COUNT):
            log(f"登录尝试第 {retry+1} 次...")
            sessid, s = login(user_list[i], passwd_list[i])
            if sessid != "-1":
                success = True
                break
            time.sleep(10) # 登录失败后多等一会儿
        
        if not success:
            log(f"账号 {user_list[i]} 最终登录失败")
            continue
        
        servers = get_servers(sessid, s)
        for k, can_renew in servers.items():
            if can_renew:
                log(f"正在续期 ServerID: {k}...")
                if renew(sessid, s, passwd_list[i], k): log(f"ServerID: {k} 续期成功")
                else: log(f"ServerID: {k} 续期失败")
            else: log(f"ServerID: {k} 无需续期")
        time.sleep(5)

    if TG_BOT_TOKEN and TG_USER_ID:
        message = "<b>AutoEUServerless 日志</b>\n\n" + desp
        requests.post(f"{TG_API_HOST}/bot{TG_BOT_TOKEN}/sendMessage", data={"chat_id": TG_USER_ID, "text": message, "parse_mode": "HTML"})

if __name__ == "__main__":
    main_handler(None, None)
