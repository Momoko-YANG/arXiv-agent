#!/usr/bin/env python3
"""
测试脚本 - 使用模拟数据演示功能
"""

from arxiv_advanced import ArxivDatabase
from datetime import datetime

# 模拟论文数据
mock_papers = [
    {
        'arxiv_id': '2402.12345',
        'title': 'Advances in Large Language Models: A Survey',
        'summary': 'This paper presents a comprehensive survey of recent advances in large language models...',
        'authors': ['Alice Smith', 'Bob Johnson', 'Carol Williams'],
        'categories': ['cs.AI', 'cs.CL'],
        'published': '2024-02-12T10:00:00Z',
        'pdf_url': 'https://arxiv.org/pdf/2402.12345'
    },
    {
        'arxiv_id': '2402.12346',
        'title': 'Diffusion Models for Image Generation',
        'summary': 'We propose a new approach to image generation using diffusion models...',
        'authors': ['David Lee', 'Emma Davis'],
        'categories': ['cs.CV', 'cs.LG'],
        'published': '2024-02-12T11:30:00Z',
        'pdf_url': 'https://arxiv.org/pdf/2402.12346'
    },
    {
        'arxiv_id': '2402.12347',
        'title': 'Reinforcement Learning with Transformers',
        'summary': 'This work explores the application of transformer architectures in reinforcement learning...',
        'authors': ['Frank Miller', 'Grace Chen', 'Henry Zhang', 'Iris Wang'],
        'categories': ['cs.LG', 'cs.AI'],
        'published': '2024-02-12T14:00:00Z',
        'pdf_url': 'https://arxiv.org/pdf/2402.12347'
    },
]

def test_database():
    """测试数据库功能"""
    print("=" * 80)
    print("测试数据库功能")
    print("=" * 80)
    
    # 创建数据库
    db = ArxivDatabase(db_path='test_arxiv.db')
    
    # 插入模拟数据
    print("\n插入论文...")
    for paper in mock_papers:
        is_new = db.insert_paper(paper)
        status = "新增" if is_new else "重复"
        print(f"  [{status}] {paper['title']}")
    
    # 尝试重复插入
    print("\n尝试重复插入第一篇论文...")
    is_new = db.insert_paper(mock_papers[0])
    print(f"  结果: {'新增' if is_new else '已存在，跳过'}")
    
    # 获取统计信息
    print("\n数据库统计:")
    stats = db.get_stats()
    print(f"  总论文数: {stats['total_papers']}")
    print(f"  总作者数: {stats['total_authors']}")
    print(f"  分类统计:")
    for cat, count in stats['category_counts'].items():
        print(f"    {cat}: {count} 篇")
    
    # 搜索功能
    print("\n搜索包含 'transformer' 的论文:")
    results = db.search_papers('transformer')
    for paper in results:
        print(f"  - {paper['title']}")
    
    # 搜索包含 'diffusion' 的论文
    print("\n搜索包含 'diffusion' 的论文:")
    results = db.search_papers('diffusion')
    for paper in results:
        print(f"  - {paper['title']}")
    
    # 获取最近的论文
    print(f"\n获取最近 30 天的论文:")
    recent = db.get_recent_papers(days=30)
    for paper in recent:
        print(f"  - {paper['title']} ({paper['published']})")
    
    db.close()
    print("\n测试完成！数据库文件: test_arxiv.db")
    print("=" * 80)


def test_formatting():
    """测试格式化输出"""
    from arxiv_agent import ArxivAgent
    
    print("\n" + "=" * 80)
    print("测试格式化输出")
    print("=" * 80 + "\n")
    
    agent = ArxivAgent()
    
    for i, paper in enumerate(mock_papers, 1):
        print(f"论文 {i}:")
        print(agent.format_paper(paper))


if __name__ == '__main__':
    # 运行测试
    test_database()
    test_formatting()
    
    print("\n" + "=" * 80)
    print("✅ 所有测试完成！")
    print("=" * 80)
    print("\n提示:")
    print("1. 查看生成的数据库: test_arxiv.db")
    print("2. 实际使用时，替换为真实的 arXiv API 数据")
    print("3. 参考 README.md 了解更多用法")
