# loadtest/locustfile.py
#
# 用法：locust -f loadtest/locustfile.py --host http://localhost:8000
# 浏览器开 http://localhost:8089 设并发开跑；或用 README 里的 headless 命令。
#
# 设计：测试开始时"全局登录一次 + 建一个就诊"，所有虚拟用户共享 token/encounter。
#   - 登录只发一次 → 不会被 Phase 6 的"登录 5/分钟 限流"卡住
#   - 用真实 encounter id → generate 路径有效
# 真实账号来自 seed(dr.smith)，可用环境变量 LOAD_EMAIL / LOAD_PASSWORD 覆盖。
import os

import requests
from locust import HttpUser, between, events, task

# 全局共享：测试开始时填充
TOKEN = ""
ENCOUNTER_ID = ""


@events.test_start.add_listener
def _setup(environment, **_):
    """测试启动钩子：登录拿 token，并建一个就诊供 generate 复用。"""
    global TOKEN, ENCOUNTER_ID
    host = environment.host or "http://localhost:8000"
    email = os.getenv("LOAD_EMAIL", "dr.smith@clinic.example.com")
    password = os.getenv("LOAD_PASSWORD", "Provider123!")

    r = requests.post(f"{host}/api/auth/login",
                      json={"email": email, "password": password}, timeout=10)
    r.raise_for_status()                       # 账号错就直接报错，别让整场测试空跑
    TOKEN = r.json()["access_token"]

    h = {"Authorization": f"Bearer {TOKEN}"}
    er = requests.post(f"{host}/api/encounters",
                       json={"first_name": "Load", "last_name": "Test", "dob": "1980-01-01"},
                       headers=h, timeout=10)
    er.raise_for_status()
    ENCOUNTER_ID = er.json()["id"]
    print(f"[loadtest] login ok; encounter_id={ENCOUNTER_ID}")


class ScribeUser(HttpUser):
    wait_time = between(1, 3)   # 模拟真人节奏；想极限压吞吐可改成 between(0, 0)

    def on_start(self):
        self.headers = {"Authorization": f"Bearer {TOKEN}"}

    @task(4)                                   # 检索更频繁
    def search_icd(self):
        self.client.get("/api/icd10/search?q=hypertension",
                        headers=self.headers, name="/api/icd10/search")

    @task(1)                                   # 生成贵、频率低
    def generate(self):
        if not ENCOUNTER_ID:
            return
        # 注意：默认会真实调用大模型并计费！测吞吐时请走 mock(见 README：清空 API key)。
        self.client.post(f"/api/encounters/{ENCOUNTER_ID}/generate",
                         json={"transcript": "Follow-up visit, BP 130/82, continue meds."},
                         headers=self.headers, name="/api/encounters/[id]/generate")
