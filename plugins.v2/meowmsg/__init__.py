import requests
from typing import List, Dict, Any, Optional
from app.core.event import EventType, eventmanager
from app.core.plug_in import _PluginBase
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time

class FeishuPlugin(_PluginBase):
    # =====【关键修正1】显式定义插件ID（必须与目录名完全一致）=====
    plugin_id = "feishu"  # 小写！与plugins/feishu目录名严格匹配
    
    # 插件元数据
    plugin_name = "飞书机器人"
    plugin_desc = "飞书消息通知插件，支持交互式按钮和长连接优化"
    plugin_version = "1.2.0"
    plugin_icon = "https://lf3-static.bytednsdoc.com/obj/eden-cn/ylaelkeh7nuhfnuhf/modern/845f8e9e1f0c0f0e0f0e0f0e0f0e0f0e.png"
    plugin_author = "MoviePilot Community"
    plugin_type = "notify"
    
    # 预填配置（用户安装后可直接使用）
    plugin_config = {
        "enabled": True,
        "feishu_app_id": "cli_a90f0e54aab05bde",
        "feishu_app_secret": "FhMr2lnHwj16NBlLaGXrzfSkeUspovsR",
        "use_long_connection": True
    }
    
    def __init__(self):
        super().__init__()
        self._session = None
        self._access_token = None
        self._token_expiry = 0
        # 【关键】不在__init__中做任何网络操作！仅初始化变量
        self.debug("✅ FeishuPlugin 实例化完成 (plugin_id=feishu)")

    # =====【关键修正2】必须实现get_name方法=====
    def get_name(self) -> str:
        """返回插件名称（MoviePilot v2 必需方法）"""
        return self.plugin_name

    def init_plugin(self, config: dict = None):
        """插件初始化（安全模式：无网络阻塞）"""
        if config:
            self.plugin_config.update(config)
        
        # 仅根据配置初始化会话（无网络请求）
        if self.plugin_config.get("use_long_connection", True) and not self._session:
            self._init_session()
            self.info("🔌 长连接会话已初始化 (Keep-Alive + 连接池)")
        
        self.info(f"🎉 飞书插件初始化成功 | AppID: {self.plugin_config.get('feishu_app_id')[:10]}...")

    def _init_session(self):
        """初始化长连接会话（无网络请求）"""
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=retries,
            pool_block=False
        )
        session.mount("https://", adapter)
        session.headers.update({"Connection": "keep-alive"})
        self._session = session

    def _get_access_token(self) -> Optional[str]:
        """安全获取token（带缓存）"""
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token
        
        app_id = self.plugin_config.get("feishu_app_id")
        app_secret = self.plugin_config.get("feishu_app_secret")
        if not app_id or not app_secret:
            self.warn("❌ 飞书凭证未配置")
            return None
        
        url = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
        try:
            session = self._session or requests.Session()
            resp = session.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
            data = resp.json()
            if data.get("code") == 0:
                self._access_token = data["app_access_token"]
                self._token_expiry = time.time() + 5400
                return self._access_token
            self.error(f"❌ Token获取失败: {data}")
        except Exception as e:
            self.error(f"❌ Token请求异常: {str(e)}")
        return None

    def post_message(self, channel: str, title: str, text: str = "", 
                    userid: str = None, buttons: List[List[Dict]] = None, **kwargs):
        """发送飞书消息（使用长连接）"""
        token = self._get_access_token()
        if not token:
            return False
        
        # 构建交互卡片（适配飞书最新API）
        card = {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": text or " "}}]
        }
        
        if buttons:
            for row in buttons:
                actions = []
                for btn in row:
                    actions.append({
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": btn["text"]},
                        "type": "primary" if btn.get("primary") else "default",
                        "value": {"type": "callback", "data": btn["callback_data"]}
                    })
                card["elements"].append({"tag": "action", "actions": actions})
        
        try:
            session = self._session or requests.Session()
            resp = session.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "receive_id": channel,
                    "msg_type": "interactive",
                    "content": card
                },
                timeout=15
            )
            result = resp.json()
            if result.get("code") == 0:
                self.info(f"✅ 消息已发送至 {channel} (长连接复用)")
                return True
            self.error(f"❌ 消息发送失败: {result}")
        except Exception as e:
            self.error(f"❌ 消息发送异常: {str(e)}")
        return False

    # ===== 必需方法（严格遵循MoviePilot v2规范）=====
    def get_state(self) -> bool:
        """返回插件状态（无异常抛出）"""
        return bool(
            self.plugin_config.get("enabled") and
            self.plugin_config.get("feishu_app_id") and
            self.plugin_config.get("feishu_app_secret")
        )

    def stop(self):
        """清理资源"""
        if self._session:
            self._session.close()
            self._session = None
        self._access_token = None
        self.info("⏹️ 飞书插件已停止")

    def get_page(self) -> Dict[str, Any]:
        """返回配置页面（必须返回有效结构）"""
        return {
            "name": "飞书配置",
            "config": [
                {"component": "switch", "label": "启用插件", "key": "enabled", "value": self.plugin_config.get("enabled", True)},
                {"component": "input", "label": "飞书App ID", "placeholder": "cli_xxx", "value": self.plugin_config.get("feishu_app_id", ""), "key": "feishu_app_id"},
                {"component": "input", "label": "飞书App Secret", "placeholder": "xxx", "value": self.plugin_config.get("feishu_app_secret", ""), "key": "feishu_app_secret"},
                {"component": "switch", "label": "启用长连接优化", "key": "use_long_connection", "value": self.plugin_config.get("use_long_connection", True)}
            ]
        }

    def update_config(self, config: dict):
        """更新配置"""
        old_enabled = self.plugin_config.get("enabled")
        self.plugin_config.update(config)
        # 重置token（配置变更后需重新认证）
        self._access_token = None
        self._token_expiry = 0
        if config.get("enabled") != old_enabled:
            self.info(f"🔄 插件状态变更: {'启用' if config.get('enabled') else '禁用'}")

    # ===== 交互功能 =====
    def _send_main_menu(self, channel: str):
        buttons = [
            [{"text": "🎬 媒体库", "callback_data": "media", "primary": True}, {"text": "🔍 搜索", "callback_data": "search"}],
            [{"text": "⚙️ 设置", "callback_data": "settings"}]
        ]
        self.post_message(channel, "🤖 MoviePilot 飞书助手", "点击下方按钮开始操作：", buttons=buttons)

    def get_command(self) -> List[Dict[str, Any]]:
        return [{
            "cmd": "/feishu",
            "event": EventType.PluginAction,
            "desc": "发送飞书交互菜单",
            "category": "通知",
            "data": {"action": "send_feishu_menu"}
        }]

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event):
        if event.event_data.get("action") == "send_feishu_menu":
            channel = event.event_data.get("channel") or event.event_data.get("user")
            if channel:
                self._send_main_menu(channel)
                self.info(f"📤 已发送菜单至 {channel}")
