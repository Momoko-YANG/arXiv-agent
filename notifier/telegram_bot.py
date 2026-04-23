"""
Telegram 通知器 — 推送日报消息 + 报告文件 + 反馈收集

v3 新增:
  - 每篇论文带 ⭐/👎 inline 按钮
  - 后台线程 getUpdates 监听回调
  - 反馈存入数据库（供自适应评分使用）
"""

import time
import threading
import requests
from datetime import datetime
from typing import Dict, List, Callable, Optional


TELEGRAM_MAX_MSG_LEN = 4096


class TelegramNotifier:
    """Telegram Bot 通知器"""

    def __init__(self, token: str, chat_id: str,
                 feedback_callback: Callable = None):
        """
        Args:
            token:             Bot token
            chat_id:           目标 chat ID
            feedback_callback: 反馈回调 fn(arxiv_id, action) → 写入数据库
        """
        self.token = token
        self.chat_id = chat_id
        self._feedback_cb = feedback_callback
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._update_offset = 0
        self._listener_started = False

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    # ------------------------------------------------------------------
    # 底层 API
    # ------------------------------------------------------------------

    def _request(self, method: str, **kwargs):
        """带重试的 Telegram Bot API 请求"""
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        for attempt in range(3):
            try:
                resp = requests.post(url, timeout=60, **kwargs)
                if resp.status_code == 429:
                    retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                    print(f"  ⏳ Telegram 限流，等待 {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                if attempt < 2:
                    wait = 2 ** (attempt + 1)
                    print(f"  ⚠️  Telegram 请求失败，{wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    raise
        return None

    def send_message(self, text: str):
        """发送文本消息（自动分段）"""
        chunks = [text[i:i + TELEGRAM_MAX_MSG_LEN]
                  for i in range(0, len(text), TELEGRAM_MAX_MSG_LEN)]
        for chunk in chunks:
            self._request("sendMessage", json={
                "chat_id": self.chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            })
            if len(chunks) > 1:
                time.sleep(0.5)

    def send_document(self, file_path: str, caption: str = ""):
        """发送文件"""
        with open(file_path, "rb") as f:
            self._request(
                "sendDocument",
                data={"chat_id": self.chat_id, "caption": caption[:1024]},
                files={"document": f},
            )

    def send_message_with_buttons(self, text: str, arxiv_id: str):
        """发送带反馈按钮的消息"""
        reply_markup = {
            "inline_keyboard": [[
                {"text": "⭐ 感兴趣", "callback_data": f"star:{arxiv_id}"},
                {"text": "👎 不相关", "callback_data": f"dismiss:{arxiv_id}"},
                {"text": "📖 已读", "callback_data": f"read:{arxiv_id}"},
            ]]
        }
        chunks = [text[i:i + TELEGRAM_MAX_MSG_LEN]
                  for i in range(0, len(text), TELEGRAM_MAX_MSG_LEN)]
        for idx, chunk in enumerate(chunks):
            payload = {
                "chat_id": self.chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }
            # 只在最后一个 chunk 加按钮
            if idx == len(chunks) - 1:
                payload["reply_markup"] = reply_markup
            self._request("sendMessage", json=payload)
            if len(chunks) > 1:
                time.sleep(0.5)

    # ------------------------------------------------------------------
    # 反馈监听器（后台线程）
    # ------------------------------------------------------------------

    def start_callback_listener(self):
        """启动后台线程监听 Telegram inline 按钮回调"""
        if not self.configured or not self._feedback_cb:
            return
        if self._listener_started:
            return
        self._prime_update_offset()
        self._stop_event.clear()
        self._listener_thread = threading.Thread(
            target=self._poll_updates, daemon=True,
        )
        self._listener_thread.start()
        self._listener_started = True
        print("  📡 Telegram 反馈监听已启动")

    def stop_callback_listener(self):
        """停止监听"""
        self._stop_event.set()
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=5)
        self._listener_started = False

    def _prime_update_offset(self):
        """启动监听前跳过历史 update，避免重启后重复消费旧回调。"""
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        try:
            resp = requests.get(url, params={"timeout": 1}, timeout=5)
            if resp.status_code != 200:
                return
            data = resp.json()
            results = data.get("result", [])
            if results:
                self._update_offset = results[-1]["update_id"] + 1
        except requests.RequestException:
            pass

    def _poll_updates(self):
        """长轮询 getUpdates，处理 callback_query"""
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        while not self._stop_event.is_set():
            try:
                resp = requests.get(url, params={
                    "offset": self._update_offset,
                    "timeout": 30,
                    "allowed_updates": '["callback_query"]',
                }, timeout=35)
                if resp.status_code != 200:
                    time.sleep(5)
                    continue

                data = resp.json()
                for update in data.get("result", []):
                    self._update_offset = update["update_id"] + 1
                    cb = update.get("callback_query")
                    if not cb:
                        continue

                    cb_data = cb.get("data", "")
                    if ":" not in cb_data:
                        continue

                    action, arxiv_id = cb_data.split(":", 1)
                    if action in ("star", "dismiss", "read"):
                        source_id = cb.get("id") or str(update["update_id"])
                        self._feedback_cb(arxiv_id, action, source_id)
                        # 回答回调（消除 Telegram 的加载动画）
                        labels = {"star": "⭐ 已标记", "dismiss": "👎 已忽略", "read": "📖 已记录"}
                        self._answer_callback(cb["id"], labels.get(action, "已记录"))

            except Exception:
                time.sleep(5)

    def _answer_callback(self, callback_query_id: str, text: str):
        """回答 callback query"""
        try:
            self._request("answerCallbackQuery", json={
                "callback_query_id": callback_query_id,
                "text": text,
            })
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 高级方法：推送日报
    # ------------------------------------------------------------------

    def send_daily_report(self, papers: List[Dict],
                          summaries: Dict[str, str],
                          report_file: str = None):
        """
        推送完整日报：消息 + 文件

        Args:
            papers:      Top N 论文列表
            summaries:   {arxiv_id: summary} 摘要字典
            report_file: Markdown 报告文件路径（可选）
        """
        if not self.configured:
            print("  ⚠️  未配置 Telegram，跳过推送")
            return

        today = datetime.now().strftime("%Y-%m-%d")

        if not papers:
            self.send_message(f"📭 arXiv 智能日报 {today}\n\n今日无特别相关的论文。")
            return

        # ---- 1. 头部消息 ----
        header = (
            f"🤖 arXiv 智能日报 {today}\n"
            f"相关论文：{len(papers)} 篇\n"
        )
        self.send_message(header)

        # ---- 2. 每篇论文单独发送（带反馈按钮）----
        for i, paper in enumerate(papers[:10], 1):
            title = paper["title"]
            if len(title) > 80:
                title = title[:77] + "..."
            arxiv_url = f"https://arxiv.org/abs/{paper['arxiv_id']}"

            # 元数据标签
            score = paper.get("quality_score", 0)
            score_tag = f"[{score:.0f}分]" if score > 0 else ""

            citations = paper.get("s2_citation_count", 0)
            cite_tag = f"引用:{citations}" if citations > 0 else ""

            if paper.get("cr_published"):
                venue = paper.get("cr_journal", "") or paper.get("s2_venue", "")
                pub_tag = f"✅{venue}" if venue else "✅已发表"
            elif paper.get("s2_venue"):
                pub_tag = f"📋{paper['s2_venue']}"
            else:
                pub_tag = "📝预印本"

            meta = " | ".join(p for p in [score_tag, cite_tag, pub_tag] if p)

            # 组装单篇消息
            paper_lines = [f"{i}. {title}", f"   {meta}"]

            # 作者信息（优先 S2，缺失则回退 arXiv）
            s2_authors = paper.get("s2_authors", [])
            valid_s2_names = [
                (a.get("name") or "").strip()
                for a in s2_authors
                if (a.get("name") or "").strip()
            ]
            if valid_s2_names:
                author_text = ", ".join(valid_s2_names[:3])
                if len(valid_s2_names) > 3:
                    author_text += "..."
            else:
                arxiv_authors = paper.get("authors", []) or []
                author_text = ", ".join(arxiv_authors[:3]) if arxiv_authors else "未知作者"
                if len(arxiv_authors) > 3:
                    author_text += "..."
            paper_lines.append(f"   作者: {author_text}")
            paper_lines.append(f"   {arxiv_url}")

            # 摘要（bullet-point 逐行展示）
            if paper["arxiv_id"] in summaries:
                for bullet in summaries[paper["arxiv_id"]].strip().split("\n"):
                    bullet = bullet.strip()
                    if bullet:
                        paper_lines.append(f"   {bullet}")

            # 每篇论文单独发送（带 ⭐/👎 反馈按钮）
            paper_text = "\n".join(paper_lines)
            try:
                if self._feedback_cb:
                    self.send_message_with_buttons(paper_text, paper["arxiv_id"])
                else:
                    self.send_message(paper_text)
                time.sleep(0.3)
            except Exception as e:
                print(f"  ⚠️  论文 {i} 发送失败: {e}")

        if len(papers) > 10:
            try:
                self.send_message(f"... 还有 {len(papers) - 10} 篇，请查看完整报告附件")
            except Exception:
                pass

        print("  📨 Telegram 消息已发送")

        # ---- 3. 报告文件 ----
        if report_file:
            try:
                self.send_document(
                    report_file,
                    caption=f"📊 arXiv 智能日报 {today}（{len(papers)} 篇）",
                )
                print("  📎 Telegram 报告文件已发送")
            except Exception as e:
                print(f"  ⚠️  Telegram 文件发送失败: {e}")
