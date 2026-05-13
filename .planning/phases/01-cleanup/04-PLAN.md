---
phase: 01-cleanup
plan: 04
type: execute
wave: 2
depends_on:
  - "01-PLAN.md"
  - "02-PLAN.md"
  - "03-PLAN.md"
files_modified:
  - backend/app/api/simulation.py
  - .env.example
autonomous: true
must_haves:
  truths:
    - All Chinese strings in the backend were found exclusively in simulation.py (350 lines) and .env.example — no other .py file contains Chinese characters
    - simulation.py has two categories of Chinese content: (a) API docstrings that mix Chinese and English, and (b) logger calls and inline comments with Chinese text
    - The Chinese in docstrings is used to describe API request/response shapes — these must be translated to English
    - Chinese logger strings (e.g. logger.error, logger.warning, logger.info with Chinese f-strings) must be translated to English
    - .env.example is entirely in Chinese — it must be fully rewritten in English
    - Plans 01, 02, and 03 must be complete before this plan runs (Plan 02 already fixes one Chinese string at line 460; Plan 03 may add new English content to .env.example — both changes must be present before this sweep)
  artifacts:
    - simulation.py with all Chinese text replaced by English equivalents
    - .env.example fully in English
  key_links: []
---

<objective>
Complete the Chinese-to-English string sweep across `backend/app/api/simulation.py` and `.env.example`.
Plans 01–03 handle the service files and config; this plan handles the API layer and the env template.

Purpose: No Chinese text remains anywhere in the codebase after Phase 1.
Output: simulation.py and .env.example are 100% English.
</objective>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@backend/app/api/simulation.py
</context>

<tasks>

<task type="auto">
  <name>Task 1.5a: Translate Chinese docstrings and inline comments in simulation.py</name>
  <files>backend/app/api/simulation.py</files>
  <action>
Run a targeted find-and-replace pass over `backend/app/api/simulation.py`. The full file is 2711 lines.
All Chinese content falls into these categories and locations:

**Category A — Docstring lines with Chinese mixed into otherwise-English docstrings**

Line 244:
  `    1. state.json 存在且 status 为 "ready"` →
  `    1. state.json exists and status is "ready"`

Lines 364–395 (the `/prepare` docstring block) — replace the entire Chinese section:

Line 364: `    使用 GET /api/simulation/prepare/status 查询进度` →
  `    Use GET /api/simulation/prepare/status to poll progress.`

Line 366: `    特性：` → `    Features:`
Line 367: `    - 自动检测已完成的准备工作，避免重复生成` →
  `    - Auto-detects completed preparation work to avoid redundant regeneration`
Line 368: `    - 如果已准备完成，直接返回已有结果` →
  `    - If already prepared, returns existing results immediately`
Line 369: `    - 支持强制重新生成（force_regenerate=true）` →
  `    - Supports forced regeneration (force_regenerate=true)`

Line 371: `    步骤：` → `    Steps:`
Line 372: `    1. 检查是否已有完成的准备工作` → `    1. Check whether preparation is already complete`
Line 373: `    2. 从Zep图谱读取并过滤实体` → `    2. Read and filter entities from the Zep graph`
Line 374: `    3. 为每个实体生成OASIS Agent Profile（带重试机制）` →
  `    3. Generate an OASIS Agent Profile for each entity (with retry logic)`
Line 375: `    4. LLM智能生成模拟配置（带重试机制）` →
  `    4. Use the LLM to intelligently generate simulation config (with retry logic)`
Line 376: `    5. 保存配置文件和预设脚本` → `    5. Save config files and preset scripts`

Line 381: `    // 可选，指定实体类型` → `    // optional, specify entity types`
Line 382: `    // 可选，是否用LLM生成人设` → `    // optional, whether to use LLM for profiles`
Line 383: `    // 可选，并行生成人设数量，默认5` →
  `    // optional, parallel profile generation count, default 5`
Line 384: `    // optional, force regeneration，默认false` →
  `    // optional, force regeneration, default false`

Line 392: `    "task_id": "task_xxxx",           // 新任务时返回` →
  `    "task_id": "task_xxxx",           // returned for new tasks`
Line 394: `    "message": "准备任务已启动|已有完成的准备工作",` →
  `    "message": "preparation started | preparation already complete",`
Line 395: `    "already_prepared": true|false    // 是否已准备完成` →
  `    "already_prepared": true|false    // whether preparation is already complete`

**Category B — Inline comments in code (not docstrings)**

Line 423: `        # 检查是否强制重新生成` → `        # Check whether force_regenerate was requested`
Line 425: `        logger.info(f"开始处理 /prepare 请求: simulation_id={simulation_id}, force_regenerate={force_regenerate}")` →
  `        logger.info(f"Processing /prepare request: simulation_id={simulation_id}, force_regenerate={force_regenerate}")`
Line 427: `        # 检查是否已经准备完成（避免重复生成）` →
  `        # Check whether preparation is already complete (avoid redundant regeneration)`
Line 429: `            logger.debug(f"检查Simulation {simulation_id} 是否已准备完成...")` →
  `            logger.debug(f"Checking whether simulation {simulation_id} is already prepared...")`
Line 431: `            logger.debug(f"检查结果: is_prepared={is_prepared}, prepare_info={prepare_info}")` →
  `            logger.debug(f"Check result: is_prepared={is_prepared}, prepare_info={prepare_info}")`
Line 433: `                logger.info(f"Simulation {simulation_id} 已准备完成，跳过重复生成")` →
  `                logger.info(f"Simulation {simulation_id} is already prepared; skipping regeneration")`
Line 439: `                        "message": "已有完成的准备工作，无需重复生成",` →
  `                        "message": "Preparation already complete; no regeneration needed",`
Line 445: `                logger.info(f"Simulation {simulation_id} 未准备完成，将启动准备任务")` →
  `                logger.info(f"Simulation {simulation_id} is not yet prepared; starting preparation task")`
Line 447: `        # 从项目获取必要信息` → `        # Load required info from the project`
Line 455: `        # 获取模拟需求` → `        # Get simulation requirement`
Line 463: `        # 获取文档文本` → `        # Get document text`
Line 470: `        # ========== 同步获取实体数量（在后台任务启动前） ==========` →
  `        # ========== Synchronously fetch entity count (before the background task starts) ==========`
Line 471: `        # 这样前端在调用prepare后立即就能获取到预期Agent总数` →
  `        # This lets the frontend get the expected total agent count immediately after calling /prepare`
Line 473: `            logger.info(f"同步获取实体数量: graph_id={state.graph_id}")` →
  `            logger.info(f"Synchronously fetching entity count: graph_id={state.graph_id}")`
Line 475: `            # 快速读取实体（不需要边信息，只统计数量）` →
  `            # Fast entity read (no edge data needed; counting only)`
Line 479: `                enrich_with_edges=False  # 不获取边信息，加快速度` →
  `                enrich_with_edges=False  # skip edge data for speed`
Line 481: `            # 保存实体数量到状态（供前端立即获取）` →
  `            # Store entity count in state (so the frontend can read it immediately)`
Line 484: `            logger.info(f"预期实体数量: {filtered_preview.filtered_count}, 类型: {filtered_preview.entity_types}")` →
  `            logger.info(f"Expected entity count: {filtered_preview.filtered_count}, types: {filtered_preview.entity_types}")`
Line 486: `            logger.warning(f"同步获取实体数量失败（将在后台任务中重试）: {e}")` →
  `            logger.warning(f"Synchronous entity count fetch failed (will retry in background task): {e}")`
Line 487: `            # 失败不影响后续流程，后台任务会重新获取` →
  `            # Failure here does not block the flow; the background task will retry`
Line 489: `        # 创建异步任务` → `        # Create async task`
Line 499: `        # 更新模拟状态（包含预先获取的实体数量）` →
  `        # Update simulation state (includes the pre-fetched entity count)`
Line 503: `        # 定义后台任务` → `        # Define the background task`
Line 510: `                    message="开始准备模拟环境..."` →
  `                    message="Starting simulation environment preparation..."`
Line 513: `                # 准备模拟（带进度回调）` → `                # Prepare simulation (with progress callback)`
Line 514: `                # 存储阶段进度详情` → `                # Store stage progress details`
Line 518: `                    # 计算总进度` → `                    # Calculate overall progress`
Line 529: `                    # 构建详细进度信息` → `                    # Build detailed progress info`
Line 531: `                        "reading": "读取图谱实体",` → `                        "reading": "Reading graph entities",`
Line 532: `                        "generating_profiles": "生成Agent人设",` → `                        "generating_profiles": "Generating agent profiles",`
Line 533: `                        "generating_config": "生成模拟配置",` → `                        "generating_config": "Generating simulation config",`
Line 534: `                        "copying_scripts": "准备模拟脚本"` → `                        "copying_scripts": "Preparing simulation scripts"`
Line 540: `                    # 更新阶段详情` → `                    # Update stage details`
Line 549: `                    # 构建详细进度信息` → `                    # Build detailed progress info`
Line 562: `                    # 构建简洁消息` → `                    # Build concise message`
Line 588: `                # 任务完成` → `                # Task complete`
Line 595: `                logger.error(f"准备模拟失败: {str(e)}")` →
  `                logger.error(f"Simulation preparation failed: {str(e)}")`
Line 598: `                # 更新模拟状态为失败` → `                # Update simulation state to failed`
Line 605: `        # 启动后台线程` → `        # Start background thread`
Line 615: `                "message": "准备任务已启动，请通过 /api/simulation/prepare/status 查询进度",` →
  `                "message": "Preparation task started; poll /api/simulation/prepare/status for progress",`
Line 617 (if present): any remaining Chinese in the return dict for `entity_types` comment.
Line 618: `                "entity_types": state.entity_types  # 实体类型列表` →
  `                "entity_types": state.entity_types  # list of entity types`

**Late-file Chinese strings (lines 2515–2711)**

Line 2517: `            "platform": "reddit",          // 可选，平台类型（reddit/twitter）` →
  `            "platform": "reddit",          // optional, platform type (reddit/twitter)`
Line 2518: `                                           // 不指定则返回两个平台的所有历史` →
  `                                           // omit to return history for both platforms`
Line 2520: `            "limit": 100                   // 可选，返回数量，默认100` →
  `            "limit": 100                   // optional, max records to return, default 100`
Line 2531: `                        "response": "我认为...",` → `                        "response": "I think...",`
Line 2532: `                        "prompt": "你对这件事有什么看法？",` →
  `                        "prompt": "What do you think about this?",`
Line 2545: `        platform = data.get('platform')  # 不指定则返回两个平台的历史` →
  `        platform = data.get('platform')  # omit to return history for both platforms`
Line 2571: `        logger.error(f"获取Interview历史失败: {str(e)}")` →
  `        logger.error(f"Failed to retrieve interview history: {str(e)}")`
Line 2582: `    获取模拟环境状态` → `    Get simulation environment status`
Line 2584: `    检查模拟环境是否存活（可以接收Interview命令）` →
  `    Check whether the simulation environment is alive (able to receive interview commands).`
Line 2599: `                "message": "环境正在运行，可以接收Interview命令"` →
  `                "message": "Environment is running and ready to receive interview commands"`
Line 2616: `        # 获取更详细的状态信息` → `        # Get detailed status information`
Line 2620: `            message = "环境正在运行，可以接收Interview命令"` →
  `            message = "Environment is running and ready to receive interview commands"`
Line 2622: `            message = "环境未运行或已关闭"` → `            message = "Environment is not running or has been closed"`
Line 2636: `        logger.error(f"获取环境状态失败: {str(e)}")` →
  `        logger.error(f"Failed to get environment status: {str(e)}")`
Line 2647: `    关闭模拟环境` → `    Close the simulation environment`
Line 2649: `    向模拟发送关闭环境命令，使其优雅退出等待命令模式。` →
  `    Send a close-environment command to the simulation, allowing it to exit gracefully.`
Line 2651: `    注意：这不同于 /stop 接口，/stop 会强制终止进程，` →
  `    Note: This differs from /stop. /stop forcibly terminates the process,`
Line 2652: `    而此接口会让模拟优雅地关闭环境并退出。` →
  `    whereas this endpoint lets the simulation close cleanly and exit.`
Line 2657: `            "timeout": 30                  // 可选，超时时间（秒），默认30` →
  `            "timeout": 30                  // optional, timeout in seconds, default 30`
Line 2664: `                "message": "环境关闭命令已发送",` → `                "message": "Environment close command sent",`
Line 2687: `        # 更新模拟状态` → `        # Update simulation state`
Line 2706: `        logger.error(f"关闭环境失败: {str(e)}")` →
  `        logger.error(f"Failed to close simulation environment: {str(e)}")`

Apply all replacements in a single editing pass over the file. Use the Edit tool for each unique
find/replace pair. After all edits, verify with:
`grep -c "[一-鿿]" backend/app/api/simulation.py`
which should return 0.
  </action>
  <verify>
Run: `python3 -c "
import re
with open('backend/app/api/simulation.py') as f:
    content = f.read()
matches = re.findall(r'[一-鿿]', content)
print(f'Chinese characters remaining: {len(matches)}')
"`
Expected output: `Chinese characters remaining: 0`
  </verify>
  <done>
- Zero Chinese characters remain in backend/app/api/simulation.py.
- Logger calls, docstrings, inline comments, and response message strings are all in English.
- The file can be imported without error.
  </done>
</task>

<task type="auto">
  <name>Task 1.5b: Rewrite .env.example in English</name>
  <files>.env.example</files>
  <action>
The current `.env.example` is entirely in Chinese. Fully replace its content with an English version.
Note: Plans 01–03 may have appended the `SIMULATION_AGENT_COUNT` / `SIMULATION_PROFILE_PARALLEL_COUNT`
block already. The final file must include those lines if present.

Replace the entire file content with:

```
# LLM API configuration (any OpenAI-compatible LLM API)
# Recommended: Alibaba DashScope (qwen-plus) — https://bailian.console.aliyun.com/
# Note: token usage can be significant; start with simulations under 40 rounds.
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# ===== Zep memory graph configuration =====
# Free tier is sufficient for basic usage: https://app.getzep.com/
ZEP_API_KEY=your_zep_api_key_here

# ===== Optional: faster/boosted LLM configuration =====
# If you do not use a boost model, remove or comment out the lines below.
# LLM_BOOST_API_KEY=your_api_key_here
# LLM_BOOST_BASE_URL=your_base_url_here
# LLM_BOOST_MODEL_NAME=your_model_name_here

# ===== Simulation timezone =====
# IANA timezone string used to shape agent activity patterns.
# Default: UTC
# SIMULATION_TIMEZONE=UTC

# ===== Simulation scale configuration =====
# Maximum number of agents (entities) to include in one simulation run.
# SIMULATION_AGENT_COUNT=15
# Number of agent profiles to generate in parallel.
# SIMULATION_PROFILE_PARALLEL_COUNT=5

# ===== Twitter platform weights =====
# TWITTER_RECENCY_WEIGHT=0.4
# TWITTER_POPULARITY_WEIGHT=0.3
# TWITTER_RELEVANCE_WEIGHT=0.3
# TWITTER_VIRAL_THRESHOLD=10
# TWITTER_ECHO_CHAMBER_STRENGTH=0.5

# ===== Reddit platform weights =====
# REDDIT_RECENCY_WEIGHT=0.3
# REDDIT_POPULARITY_WEIGHT=0.4
# REDDIT_RELEVANCE_WEIGHT=0.3
# REDDIT_VIRAL_THRESHOLD=15
# REDDIT_ECHO_CHAMBER_STRENGTH=0.6
```
  </action>
  <verify>
Run: `python3 -c "
import re
with open('.env.example') as f:
    content = f.read()
matches = re.findall(r'[一-鿿]', content)
print(f'Chinese characters remaining: {len(matches)}')
"`
Expected output: `Chinese characters remaining: 0`
Run: `grep "LLM_API_KEY\|ZEP_API_KEY\|SIMULATION_TIMEZONE\|SIMULATION_AGENT_COUNT" .env.example | wc -l`
Expected: 4 or more lines.
  </verify>
  <done>
- Zero Chinese characters remain in .env.example.
- All original config keys (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, ZEP_API_KEY, boost vars) are present.
- New vars from Plans 01–03 (SIMULATION_TIMEZONE, SIMULATION_AGENT_COUNT, SIMULATION_PROFILE_PARALLEL_COUNT, platform weights) are documented.
  </done>
</task>

</tasks>

<success_criteria>
1. `python3 -c "import re; f=open('backend/app/api/simulation.py').read(); print(len(re.findall(r'[一-鿿]', f)))"` prints `0`.
2. `python3 -c "import re; f=open('.env.example').read(); print(len(re.findall(r'[一-鿿]', f)))"` prints `0`.
3. `cd backend && python -c "from app.api.simulation import simulation_bp; print('OK')"` prints OK without error.
4. `grep -rn "[一-鿿]" backend/app/` returns no results (cross-check the full backend after Plans 01–04 are all applied).
</success_criteria>
