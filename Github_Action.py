# SPDX-License-Identifier: GPL-3.0-or-later

"""
euserv 自动续期脚本 (优化版)
优化点：
1. 强制获取最新邮件 (解决必须清空邮箱的问题)
2. 延长邮件获取超时时间至 60 秒
3. 增强邮件主题匹配的容错性
4. 修复邮件排序逻辑，从最新邮件开始扫描
"""
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

# 账户信息
USERNAME = os.getenv('EUSERV_USERNAME')
PASSWORD = os.getenv('EUSERV_PASSWORD')

# TrueCaptcha API 配置
TRUECAPTCHA_USERID = os.getenv('TRUECAPTCHA_USERID')
TRUECAPTCHA_APIKEY = os.getenv('TRUECAPTCHA_APIKEY')

# Gmail 邮箱 配置
IMAP_SERVER = os.getenv('IMAP_SERVER')
MAIL_ADDRESS = os.getenv('MAIL_ADDRESS')
APP_PASSWORD = os.getenv('APP_PASSWORD')
SENDER_FILTER = 'EUserv Support'
SUBJECT_FILTER = 'EUserv - PIN for the Confirmation of a Security Check'
MAX_MAILS = 15
CODE_PATTER = r"\b\d{6}\b"

# Telegram Bot 推送配置
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_USER_ID = os.getenv('TG_USER_ID')
TG_API_HOST = "https://api.telegram.org"

# 最大登录重试次数
LOGIN_MAX_RETRY_COUNT = 5
# 触发续期后等待邮件发出的基础时间
WAITING_TIME_OF_PIN = 10
# 搜索邮件的总超时时间 (增加到60秒，提高稳定性)
SEARCH_TIMEOUT = 60

CHECK_CAPTCHA_SOLVER_USAGE = True

user_agent = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
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

def login_retry(*args, **kwargs):
    def wrapper(func):
        def inner(username, password):
            max_retry = kwargs.get("max_retry", 3)
            ret, ret_session = func(username, password)
            number = 0
            if ret == "-1":
                while number < max_retry:
                    number += 1
                    log(f"[AutoEUServerless] 登录尝试第 {number} 次")
                    sess_id, session = func(username, password)
                    if sess_id != "-1":
                        return sess_id, session
                    time.sleep(5)
                return "-1", ret_session
            else:
                return ret, ret_session
        return inner
    return wrapper

def captcha_solver(captcha_image_url: str, session: requests.session) -> dict:
    response = session.get(captcha_image_url)
    encoded_string = base64.b64encode(response.content).decode('utf-8')
    url = "https://api.apitruecaptcha.org/one/gettext"
    data = {
        "userid": TRUECAPTCHA_USERID,
        "apikey": TRUECAPTCHA_APIKEY,
        "case": "mixed",
        "mode": "human",
        "data": encoded_string,
    }
    try:
        r = requests.post(url=url, json=data, timeout=20)
        return r.json()
    except:
        return {}

def handle_captcha_solved_result(solved: dict) -> str:
    if "result" in solved:
        text = solved["result"]
        log(f"[Captcha Solver] 识别原始结果: {text}")
        # 清理空格并处理简单加减法
        text = text.replace(" ", "")
        if any(op in text for op in ["+", "-", "x", "X", "*"]):
            try:
                processed_text = text.lower().replace("x", "*")
                return str(eval(re.sub(r'[^0-9*+-]', '', processed_text)))
            except:
                return text
        return text
    raise KeyError("未找到解析结果")

def get_captcha_solver_usage() -> dict:
    url = "https://api.apitruecaptcha.org/one/getusage"
    params = {"username": TRUECAPTCHA_USERID, "apikey": TRUECAPTCHA_APIKEY}
    try:
        r = requests.get(url=url, params=params, timeout=10)
        return r.json()
    except:
        return [{"date": "Error", "count": "0"}]

@login_retry(max_retry=LOGIN_MAX_RETRY_COUNT)
def login(username: str, password: str) -> (str, requests.session):
    headers = {"user-agent": user_agent}
    url = "https://support.euserv.com/index.iphp"
    captcha_image_url = "https://support.euserv.com/securimage_show.php"
    session = requests.Session()
    
    sess = session.get(url, headers=headers)
    sess_ids = re.findall("PHPSESSID=(\\w{10,100});", str(sess.headers))
    sess_id = sess_ids[0] if sess_ids else ""
    
    login_data = {
        "email": username, "password": password, "form_selected_language": "en",
        "Submit": "Login", "subaction": "login", "sess_id": sess_id,
    }
    f = session.post(url, headers=headers, data=login_data)
    
    if "To finish the login process please solve the following captcha." in f.text:
        log("[Captcha Solver] 正在进行验证码识别...")
        solved_result = captcha_solver(captcha_image_url, session)
        captcha_code = handle_captcha_solved_result(solved_result)
        log(f"[Captcha Solver] 识别的验证码是: {captcha_code}")

        if CHECK_CAPTCHA_SOLVER_USAGE:
            usage = get_captcha_solver_usage()
            log(f"[Captcha Solver] API 使用次数: {usage[0].get('count', 'N/A')}")

        f2 = session.post(url, headers=headers, data={
            "subaction": "login", "sess_id": sess_id, "captcha_code": captcha_code,
        })
        if "Logout" in f2.text or "Hello" in f2.text:
            log("[Captcha Solver] 验证通过")
            return sess_id, session
        return "-1", session
    
    if "Hello" in f.text or "Logout" in f.text:
        return sess_id, session
    return "-1", session

def get_servers(sess_id: str, session: requests.session) -> {}:
    d = {}
    url = f"https://support.euserv.com/index.iphp?sess_id={sess_id}"
    f = session.get(url)
    soup = BeautifulSoup(f.text, "html.parser")
    for tr in soup.select("#kc2_order_customer_orders_tab_content_1 .kc2_order_table tr"):
        server_id = tr.select(".td-z1-sp1-kc")
        if not server_id: continue
        action_text = tr.select(".td-z1-sp2-kc")[0].get_text()
        # 如果包含 "Contract extension possible from"，说明目前还不能续期
        can_renew = "Contract extension possible from" not in action_text
        d[server_id[0].get_text()] = can_renew
    return d

def get_mail_pin(imap_server, mail_address, app_password, sender_filter, subject_filter, max_mails, code_pattern, timeout):
    log(f"[Mail] 正在搜索最新邮件 (超时限制: {timeout}s)...")
    try:
        imap = imaplib.IMAP4_SSL(imap_server)
        imap.login(mail_address, app_password)
        imap.select("INBOX")

        start_time = time.time()
        while time.time() - start_time < timeout:
            # 优化：搜索所有邮件，我们通过 ID 排序来找最新的
            _, data = imap.search(None, "ALL")
            mail_ids = data[0].split()
            
            # 核心优化：从后往前找（最新的在前）
            for num in reversed(mail_ids[-max_mails:]):
                _, msg_data = imap.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                
                # 解析发件人
                from_ = decode_header(msg.get("From"))[0][0]
                if isinstance(from_, bytes): from_ = from_.decode()
                
                # 解析主题
                sub = decode_header(msg.get("Subject"))[0][0]
                if isinstance(sub, bytes): sub = sub.decode()

                # 增强匹配：只要包含关键词即可
                if sender_filter.lower() in from_.lower() or "euserv" in from_.lower():
                    # 如果找到了符合条件的邮件
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode()
                    else:
                        body = msg.get_payload(decode=True).decode()
                    
                    match = re.search(code_pattern, body)
                    if match:
                        pin = match.group(0)
                        # 标记已读
                        imap.store(num, '+FLAGS', '\\Seen')
                        imap.logout()
                        return pin
            
            time.sleep(5) # 每5秒检查一次
        
        imap.logout()
    except Exception as e:
        log(f"[Mail] 错误: {e}")
    return None

def renew(sess_id: str, session: requests.session, password: str, order_id: str) -> bool:
    url = "https://support.euserv.com/index.iphp"
    headers = {"user-agent": user_agent, "Referer": url}
    
    # 1. 选中订单
    session.post(url, headers=headers, data={
        "Submit": "Extend contract", "sess_id": sess_id, "ord_no": order_id,
        "subaction": "choose_order", "choose_order_subaction": "show_contract_details",
    })

    # 2. 触发 Security Check 邮件
    session.post(url, headers=headers, data={
        "sess_id": sess_id, "subaction": "show_kc2_security_password_dialog",
        "prefix": "kc2_customer_contract_details_extend_contract_", "type": "1",
    })

    log("[Mail] 已触发 PIN 码邮件发送，等待接收...")
    time.sleep(WAITING_TIME_OF_PIN)

    pin = get_mail_pin(IMAP_SERVER, MAIL_ADDRESS, APP_PASSWORD, SENDER_FILTER, SUBJECT_FILTER, MAX_MAILS, CODE_PATTER, SEARCH_TIMEOUT)

    if not pin:
        raise Exception("无法获取 PIN")

    log(f"[Mail] 成功捕获 PIN: {pin}")

    # 3. 提交 PIN 获取 Token
    res = session.post(url, headers=headers, data={
        "auth": pin, "sess_id": sess_id, "subaction": "kc2_security_password_get_token",
        "prefix": "kc2_customer_contract_details_extend_contract_", "type": 1,
        "ident": f"kc2_customer_contract_details_extend_contract_{order_id}",
    })
    
    try:
        res_json = res.json()
        if res_json.get("rs") == "success":
            token = res_json["token"]["value"]
            # 4. 最终确认续期
            session.post(url, headers=headers, data={
                "sess_id": sess_id, "ord_id": order_id,
                "subaction": "kc2_customer_contract_details_extend_contract_term", "token": token,
            })
            return True
    except:
        pass
    return False

def check(sess_id: str, session: requests.session):
    d = get_servers(sess_id, session)
    for k, v in d.items():
        if v: log(f"ServerID: {k} 状态仍然为【可续期】，可能操作未生效。")
        else: log(f"ServerID: {k} 状态确认为【无需续期】。")

def telegram():
    message = "<b>AutoEUServerless 日志</b>\n\n" + desp
    data = {"chat_id": TG_USER_ID, "text": message, "parse_mode": "HTML"}
    requests.post(f"{TG_API_HOST}/bot{TG_BOT_TOKEN}/sendMessage", data=data)

def main_handler(event, context):
    if not USERNAME or not PASSWORD:
        log("未配置账号信息")
        return

    user_list = USERNAME.strip().split()
    passwd_list = PASSWORD.strip().split()
    
    for i in range(len(user_list)):
        log(f"开始处理第 {i+1} 个账号")
        sessid, s = login(user_list[i], passwd_list[i])
        if sessid == "-1":
            log(f"账号 {user_list[i]} 登录失败")
            continue
        
        servers = get_servers(sessid, s)
        for k, can_renew in servers.items():
            if can_renew:
                log(f"正在为 ServerID: {k} 执行续期...")
                if renew(sessid, s, passwd_list[i], k):
                    log(f"ServerID: {k} 续期指令发送成功")
                else:
                    log(f"ServerID: {k} 续期失败")
            else:
                log(f"ServerID: {k} 目前无需续期")
        
        time.sleep(5)
        check(sessid, s)

    if TG_BOT_TOKEN and TG_USER_ID:
        telegram()

if __name__ == "__main__":
    main_handler(None, None)
