# Lessie AI Twitter 数字员工需求评审文档 (Hackathon MVP)

## 一、产品概述与目标

为 Lessie AI 构建一个"活体 Demo"级别的 Twitter 数字员工。其核心目标不是简单的品牌曝光，而是通过 **"先提供价值，再建立认知"** 的策略，直接在推特社交场景中展示 Lessie 的搜索能力，并将流量精准引流至具体的搜索结果页。

## 二、目标用户画像 (Target Audience)

1. **B2B 增长负责人 (Growth Operators)**：寻找高意向线索（Leads）
2. **独立开发者/初创团队**：需要低成本、高效率的获客工具
3. **招聘人员与猎头**：在热点领域（AI/Web3）快速定位专家人才

## 三、核心痛点与解决方案

**痛点**：传统的 Bot 营销由于内容空洞，极易被用户反感并触发 Twitter 垃圾邮件过滤机制。

**解决**：**Result-Driven Marketing** — 不发广告，只发答案。利用 Lessie 独有的"搜索结果分享链接"，让用户在点击链接的第一秒就看到产品的真实价值。

## 四、功能模块深度分析

### 场景一：趋势借势发帖 (Trend-Jacking Auto-Posting)

**逻辑流：**

1. **热点捕捉**：每日抓取 Twitter 实时热门词（如 #Sora, #Nvidia）
2. **Prompt 转化**：LLM 将热词转化为 Lessie 找人场景（例如："帮我找 Sora 相关的底层算法专家"）
3. **能力调用**：Lessie Skill 运行搜索并生成唯一的分享链接
4. **拟人化发布**：生成带有"人味"的口语化文案，附带 Lessie 结果链接发布

**价值**：利用热点流量进行产品能力的视觉展示。

### 场景二：意图拦截转发 (Intent-Interception Quote Repost)

**逻辑流：**

1. **意图监听**：全网搜索包含 "looking for", "anyone knows", "recommend a developer" 等找人意向的推文
2. **需求提取**：解析原推上下文，自动合成 Lessie 搜索 Prompt
3. **价值交付**：调用 Lessie 跑出结果，通过 Quote Repost (引用转发) 方式回复对方

**文案示例**：
> "帮你在 Lessie 上搜了一圈，这几位背景很 Match，清单链接自取：[结果链接]"

**价值**：外科手术般的精准获客，极高概率转化高意向用户。

### 文案与防风控引擎 (Human-like & Anti-Spam)

- **文案风格**：设定为硅谷 AI 创业者口吻，使用非模版化的口语
- **链接策略**：利用 Lessie 的动态结果链接避开固定 URL 屏蔽风险

## 五、黑客松 Demo 亮点

- **实机演示**：现场发布一条"求推荐人才"的推文，演示数字员工在 1 分钟内自动识别意图并回复精准结果清单的全过程
- **转化闭环**：强调从"推文浏览"到"点击 Lessie 结果页"的极短转化路径

## 六、System Prompt 架构（数字员工人设 "Alex"）

```
Role: 你是 Lessie AI 的高级增长官 Alex
性格：极客、热心、说话直接、不喜欢啰嗦

Tone:
1. 禁止使用 "Hello there"、"I am an AI" 等开场白
2. 模仿 Twitter 真实用户的书写习惯：句子短小、首字母偶尔不规范大写、多用连接符（如 -- ）
3. 必须在文案中体现对原推文逻辑的"理解"
   例如：如果对方在找 React 开发，你要说
   "React 开发现在确实卷，但我帮你从 Lessie 捞到了几个真正有实战经验的..."

Link Policy:
1. 不要直接扔链接，要用引导性动作
   如 "Check out the list I built for you" 或 "Details here 👇"
```

## 七、结果页转化钩子设计 (Conversion Hook)

### 结果页定制化
- 数字员工生成的分享链接标题应具有针对性
- 示例：转发回复时，链接标题自动设为 "Candidates found for [原推主昵称]"

### 注册转化路径
1. 用户点击链接 → 看到 3-5 个高质量结果（预览模式）
2. 用户想看更全信息（联系方式、完整简历）→ 提示 "Sign up for Lessie to see more"

**逻辑**：这是一种 **"High-Value Lead Magnet"**（高价值引流磁铁）

## 八、技术实现 Pipeline

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Scanner   │───▶│  Reasoner   │───▶│ API Bridge  │───▶│   Action    │
│ 推特数据抓取 │    │ LLM意图分析  │    │ Lessie API  │    │ 发帖/回复   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

### Scanner 模块
- 使用 n8n 或 Python (tweepy) 实时监听推文

### Reasoner 模块
- 将推文发给 LLM
- LLM 任务：判断意图（找人 vs 其他）+ 提取搜索参数（职位、地域、技能）

### Lessie API Bridge
- 将参数喂给 Lessie 后端
- 获取 result_id 并拼凑成 `lessie.ai/share/[id]`

### Action 模块
- 根据原推文内容，合成回复文案
- 调用 Twitter API 发出 Quote Repost

## 九、Demo 剧本（Magic Moments）

1. **Step 1**：展示 Twitter 上一个真实的热门话题（比如某大厂裁员或某项目爆火）
2. **Step 2**：展示数字员工如何"嗅"到这个话题，并自动为被裁员群体制作了一个 "Top Talent for Hire" 的 Lessie 列表
3. **Step 3**：展示这一条推文在短短几分钟内获得的点击和互动

**结论**：强调这种模式让 Lessie 从一个 **"被动搜索工具"** 变成了一个 **"主动连接资产"**。

## 十、MVP 范围

### V0.1（Hackathon）
- [ ] Scanner：固定关键词列表 + 定时抓取
- [ ] Reasoner：LLM 过滤 + 结构化
- [ ] API Bridge：调用 Lessie 搜索 + 生成分享链接
- [ ] Action：自动引用转发回复
- [ ] Demo：现场 1 分钟意图识别 + 回复演示

### V0.2+（后续迭代）
- [ ] 实时流式监控
- [ ] Dashboard 看板
- [ ] 反馈闭环 / prompt 自动优化
- [ ] 多语言支持
- [ ] A/B 文案测试
