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
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
}

desp = ""

def log(info: str):
    print(info)
    global desp
    desp += info + "\n\n"

def save_debug_page(content, filename="login_error.html"):
    """保存报错页面供 GitHub Artifacts 下载"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    log(f"⚠️ 已保存报错页面到: {filename}")

def captcha_solver(captcha_image_url: str, session: requests.Session) -> str:
    try:
        response = session.get(captcha_image_url, timeout=15)
        encoded_string = base64.b64encode(response.content).decode('utf-8')
        url = "https://api.apitruecaptcha.org/one/gettext"
        data = {
            "userid": TRUECAPTCHA_USERID,
            "apikey": TRUECAPTCHA_APIKEY,
            "data": encoded_string,
        }
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
        # 1. 访问首页获取 Cookie
        r1 = session.get(url, timeout=20)
        sess_id = ""
        sess_match = re.search(r"PHPSESSID=([^;]+)", str(r1.headers))
        if sess_match:
            sess_id = sess_match.group(1)

        # 2. 尝试登录
        login_data = {
            "email": username, 
            "password": password, 
            "subaction": "login", 
            "sess_id": sess_id,
            "Submit": "Login"
        }
        r2 = session.post(url, data=login_data, timeout=20)

        # 3. 检查是否需要验证码
        if "solve the following captcha" in r2.text:
            log("🧩 触发验证码，正在识别...")
            code = captcha_solver(captcha_image_url, session)
            log(f"🔢 识别结果: {code}")
            r2 = session.post(url, data={
                "subaction": "login", "sess_id": sess_id, "captcha_code": code
            }, timeout=20)

        # 4. 验证登录状态
        if "Logout" in r2.text or "Hello" in r2.text:
            log("✅ 登录成功")
            return sess_id, session
        else:
            # 关键：登录失败，保存现场
            log("❌ 登录失败，正在保存页面源码...")
            save_debug_page(r2.text, f"error_{username[:3]}.html")
            if "Forbidden" in r2.text or r2.status_code == 403:
                log("❗ 错误：IP 被 EUserv 封锁 (403 Forbidden)")
            elif "confirmation of a security check" in r2.text.lower():
                log("❗ 错误：触发了登录 PIN 码验证，需要更新脚本逻辑")
            
    except Exception as e:
        log(f"网络异常: {e}")
        
    return "-1", session

# --- 其余 get_servers, renew 等函数保持不变 ---
# (为了节省篇幅，此处省略，请复用上一个回复中的 get_servers, get_mail_pin, renew 和 main_handler 函数)

def main_handler(event, context):
    if not USERNAME or not PASSWORD:
        log("未设置用户名或密码")
        return
    
    user_list = USERNAME.strip().split()
    passwd_list = PASSWORD.strip().split()
    
    for i in range(min(len(user_list), len(passwd_list))):
        log(f"开始处理账号: {user_list[i]}")
        sessid, s = "-1", None
        for attempt in range(1, 4):
            log(f"第 {attempt} 次登录尝试...")
            sessid, s = login(user_list[i], passwd_list[i])
            if sessid != "-1": break
            time.sleep(10)
        
        if sessid == "-1":
            log(f"账号 {user_list[i]} 登录失败，跳过后续操作。")
            continue
        
        # ...后续续费逻辑 (get_servers, renew)...

    # 发送 TG 通知
    if TG_BOT_TOKEN and TG_USER_ID:
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", 
                      data={"chat_id": TG_USER_ID, "text": desp})

if __name__ == "__main__":
    main_handler(None, None)
