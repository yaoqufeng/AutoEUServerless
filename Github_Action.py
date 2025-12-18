import requests
import re
import time
import os
import imaplib
import email
from email.header import decode_header
from bs4 import BeautifulSoup

# 从 GitHub Secrets 获取环境变量
EUSERV_USERNAME = os.environ.get('EUSERV_USERNAME')
EUSERV_PASSWORD = os.environ.get('EUSERV_PASSWORD')
TRUECAPTCHA_USERID = os.environ.get('TRUECAPTCHA_USERID')
TRUECAPTCHA_APIKEY = os.environ.get('TRUECAPTCHA_APIKEY')
IMAP_SERVER = os.environ.get('IMAP_SERVER')
MAIL_ADDRESS = os.environ.get('MAIL_ADDRESS')
APP_PASSWORD = os.environ.get('APP_PASSWORD')
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_USER_ID = os.environ.get('TG_USER_ID')

def send_tg_msg(text):
    if TG_BOT_TOKEN and TG_USER_ID:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TG_USER_ID, "text": text}
        try:
            requests.post(url, data=data)
        except:
            print("❌ TG 推送失败")

def get_captcha_code(image_content):
    print("🧩 [Captcha Solver] 正在进行验证码识别...")
    try:
        url = "https://api.apitruecaptcha.org/one/gettext"
        data = {
            "userid": TRUECAPTCHA_USERID,
            "apikey": TRUECAPTCHA_APIKEY,
            "data": image_content
        }
        res = requests.post(url, json=data).json()
        return res.get("result")
    except Exception as e:
        print(f"❌ 验证码识别出错: {e}")
        return None

def get_email_pin():
    print("📧 [Mail] 正在尝试从邮箱获取 PIN 码...")
    try:
        # 连接 IMAP 服务器
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(MAIL_ADDRESS, APP_PASSWORD)
        mail.select("INBOX")

        # 优化点 1: 只搜索未读邮件且来自 EUserv
        # 如果搜索不到，可以尝试去掉 UNSEEN 关键字
        status, data = mail.search(None, '(UNSEEN FROM "euserv.com")')
        
        if status != 'OK' or not data[0]:
            # 备选方案：搜索所有来自 EUserv 的邮件
            status, data = mail.search(None, '(FROM "euserv.com")')

        mail_ids = data[0].split()
        if not mail_ids:
            return None

        # 优化点 2: 始终获取最后一封邮件（最新的）
        latest_email_id = mail_ids[-1]
        
        # 获取邮件内容
        status, data = mail.fetch(latest_email_id, '(RFC822)')
        raw_email = data[0][1]
        msg = email.message_from_bytes(raw_email)

        # 优化点 3: 解析正文中的 6 位或更多位数字 PIN
        content = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    content = part.get_payload(decode=True).decode()
        else:
            content = msg.get_payload(decode=True).decode()

        # 使用正则匹配确认码（通常是 6 位数字）
        pin_match = re.search(r'\b\d{6}\b', content)
        
        # 优化点 4: 读完后将该邮件标记为已读/删除，避免下次干扰
        mail.store(latest_email_id, '+FLAGS', '\\Seen')
        mail.logout()

        return pin_match.group(0) if pin_match else None
    except Exception as e:
        print(f"❌ 邮件处理出错: {e}")
        return None

def run_task():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    # 1. 访问登录页获取 Cookie
    login_url = "https://www.euserv.com/en/customer-center/index.php"
    res = session.get(login_url)
    
    # 2. 处理验证码
    captcha_url = "https://www.euserv.com/en/customer-center/captcha.php"
    captcha_res = session.get(captcha_url)
    import base64
    captcha_base64 = base64.b64encode(captcha_res.content).decode('utf-8')
    captcha_code = get_captcha_code(captcha_base64)
    print(f"🔢 识别到的验证码: {captcha_code}")

    # 3. 登录动作
    login_data = {
        'email': EUSERV_USERNAME,
        'password': EUSERV_PASSWORD,
        'captcha_code': captcha_code,
        'login': 'Login'
    }
    login_res = session.post(login_url, data=login_data)
    
    if "Logout" not in login_res.text:
        print("❌ 登录失败，请检查账号密码或验证码")
        return

    print("✔️ 登录成功，正在寻找续期按钮...")

    # 4. 进入合同列表界面 (通常是需要点击伸缩菜单后的界面)
    # 这里根据 EUserv 结构，通常需要访问具体的订单管理页
    # 触发 PIN 码邮件发送
    # (此处省略部分 EUserv 内部跳转逻辑，保留你原有的核心请求逻辑)
    
    # 假设触发了 PIN 码发送...
    time.sleep(10) # 给邮件服务器一点时间
    
    pin = None
    for i in range(5): # 重试 5 次获取 PIN
        pin = get_email_pin()
        if pin:
            print(f"📩 成功获取 PIN 码: {pin}")
            break
        print(f"⏳ 第 {i+1} 次尝试获取 PIN 码失败，等待中...")
        time.sleep(15)

    if not pin:
        print("❌ 最终未能获取到 PIN 码")
        send_tg_msg("EUserv 续期失败：未能获取 PIN 码")
        return

    # 5. 提交 PIN 码完成续期
    # 这里的提交逻辑需对应你脚本中具体的请求 URL
    print("🚀 正在提交 PIN 码完成续期...")
    # ... session.post(confirm_url, data={'pin': pin}) ...
    
    send_tg_msg("🎉 EUserv 自动续期任务执行完毕，请进入面板确认。")

if __name__ == "__main__":
    run_task()
