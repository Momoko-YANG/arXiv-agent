#!/usr/bin/env python3
"""
arXiv Daily Scraper with Scheduling
带定时任务的 arXiv 论文抓取器
"""

import schedule
import time
from datetime import datetime
from arxiv_agent import ArxivAgent
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os


class DailyArxivScraper:
    """每日定时抓取 arXiv 论文"""
    
    def __init__(self, categories: list, email_config: dict = None):
        """
        初始化定时抓取器
        
        Args:
            categories: 关注的分类列表
            email_config: 邮件配置（可选），用于发送每日摘要
                {
                    'smtp_server': 'smtp.gmail.com',
                    'smtp_port': 587,
                    'sender': 'your-email@gmail.com',
                    'password': 'your-app-password',
                    'recipients': ['recipient@example.com']
                }
        """
        self.agent = ArxivAgent(categories=categories)
        self.email_config = email_config
        self.categories = categories
    
    def daily_job(self):
        """每日执行的任务"""
        print(f"\n{'='*80}")
        print(f"开始每日抓取任务 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")
        
        # 抓取最近 1 天的论文
        papers = self.agent.fetch_recent_papers(days=1, max_results=200)
        
        if not papers:
            print("没有抓取到新论文")
            return
        
        # 保存到文件
        filename = f"arxiv_daily_{datetime.now().strftime('%Y%m%d')}.json"
        self.agent.save_to_json(papers, filename)
        
        # 生成摘要报告
        report = self._generate_report(papers)
        
        # 保存报告
        report_filename = f"arxiv_report_{datetime.now().strftime('%Y%m%d')}.txt"
        with open(report_filename, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"报告已保存到 {report_filename}")
        
        # 如果配置了邮件，发送邮件摘要
        if self.email_config:
            self._send_email_report(report, papers)
        
        print(f"\n任务完成！共处理 {len(papers)} 篇论文\n")
    
    def _generate_report(self, papers: list) -> str:
        """生成每日摘要报告"""
        report = []
        report.append(f"arXiv 每日论文摘要")
        report.append(f"日期: {datetime.now().strftime('%Y-%m-%d')}")
        report.append(f"关注分类: {', '.join(self.categories)}")
        report.append(f"论文总数: {len(papers)}")
        report.append("=" * 80)
        report.append("")
        
        # 按分类统计
        category_count = {}
        for paper in papers:
            for cat in paper['categories']:
                category_count[cat] = category_count.get(cat, 0) + 1
        
        report.append("分类统计:")
        for cat, count in sorted(category_count.items(), key=lambda x: x[1], reverse=True):
            report.append(f"  {cat}: {count} 篇")
        report.append("")
        
        # 列出所有论文（简要信息）
        report.append("=" * 80)
        report.append("论文列表:")
        report.append("=" * 80)
        report.append("")
        
        for i, paper in enumerate(papers, 1):
            report.append(f"{i}. {paper['title']}")
            report.append(f"   arXiv ID: {paper['arxiv_id']}")
            report.append(f"   作者: {', '.join(paper['authors'][:2])}{'...' if len(paper['authors']) > 2 else ''}")
            report.append(f"   分类: {', '.join(paper['categories'][:3])}")
            report.append(f"   链接: https://arxiv.org/abs/{paper['arxiv_id']}")
            report.append("")
        
        return '\n'.join(report)
    
    def _send_email_report(self, report: str, papers: list):
        """发送邮件报告"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_config['sender']
            msg['To'] = ', '.join(self.email_config['recipients'])
            msg['Subject'] = f"arXiv 每日论文摘要 - {datetime.now().strftime('%Y-%m-%d')} ({len(papers)} 篇)"
            
            # 邮件正文
            body = report
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # 发送邮件
            server = smtplib.SMTP(self.email_config['smtp_server'], 
                                 self.email_config['smtp_port'])
            server.starttls()
            server.login(self.email_config['sender'], 
                        self.email_config['password'])
            server.send_message(msg)
            server.quit()
            
            print("邮件报告已发送")
        except Exception as e:
            print(f"发送邮件失败: {e}")
    
    def run_scheduler(self, run_time: str = "09:00"):
        """
        运行定时任务
        
        Args:
            run_time: 每天执行的时间，格式 "HH:MM"
        """
        print(f"定时任务已启动，将在每天 {run_time} 执行")
        print("按 Ctrl+C 停止\n")
        
        # 设置定时任务
        schedule.every().day.at(run_time).do(self.daily_job)
        
        # 立即执行一次（可选）
        # self.daily_job()
        
        # 持续运行
        while True:
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次


def main():
    """主函数"""
    # 配置要关注的分类
    categories = [
        'cs.AI',  # Artificial Intelligence
        'cs.LG',  # Machine Learning
        'cs.CV',  # Computer Vision
        'cs.CL',  # Computation and Language (NLP)
        'cs.NE',  # Neural and Evolutionary Computing
    ]
    
    # 邮件配置（可选，如果不需要邮件通知可以设为 None）
    email_config = None
    # email_config = {
    #     'smtp_server': 'smtp.gmail.com',
    #     'smtp_port': 587,
    #     'sender': 'your-email@gmail.com',
    #     'password': 'your-app-password',  # Gmail 需要使用应用专用密码
    #     'recipients': ['your-email@gmail.com']
    # }
    
    # 创建调度器
    scraper = DailyArxivScraper(categories=categories, email_config=email_config)
    
    # 选择运行模式
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--once':
        # 单次运行模式
        print("单次运行模式")
        scraper.daily_job()
    else:
        # 定时运行模式（每天早上 9:00）
        scraper.run_scheduler(run_time="09:00")


if __name__ == '__main__':
    main()
