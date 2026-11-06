# Phase 7 完成报告：搜索与体验优化

> 完成日期：2026-11-06
> 代码基线：Phase 1 + 2 + 3 + 4 + 5 + 6 工作树
> 验证环境：Python 3.11.15 / PySide6 6.11.1 / pytest 9.1.1（Windows）
> 验证结果：**437 项测试全部通过**（Phase 6 基线上新增 73 项）

---

## 一、结论

`_mds/plan.md` 第 35 节 Phase 7 的 9 项检查全部完成，`_mds/stage.md`
Phase 7 的 7.1 ~ 7.4 全部落地：

| stage.md 任务 | 实现 | 验证 |
|---|---|---|
| 7.1 `utils/settings_manager.py` | `WindowGeometry`；`save/load_window_geometry()`；展开状态按 **显示路径** 保存/恢复；`save/load_expanded_nodes()` 兼容 stage 的节点 ID 形式；搜索侧栏可见性 | `tests/test_settings_manager.py`（12 项） |
| 7.2 搜索 | 主窗口顶部搜索框 + 防抖（250 ms）+ 右侧结果 Dock；节点名称 / PDF 路径匹配；结果列出节点的 **全部位置**；单击位置展开并选中对应显示实例；独立 `SearchDialog`（Ctrl+Shift+F）复用同一结果组件 | `tests/test_search_service.py`（12 项）、`tests/test_search_ui.py`（9 项） |
| 7.3 日志系统 | `RotatingFileHandler` 输出 `logs/AP_Library_Manager_log.txt`（2 MB × 3）；`logging.level` 配置；`log_exception()` 写完整 traceback；启动时记录 Python/Qt/路径；退出时 flush | `tests/test_logger.py`（5 项） |
| 7.4 优化 | 窗口大小/位置/最大化记忆；展开状态记忆；批量重新定位；`describe_error()` 把 SQLite/文件/JSON 异常翻译为可操作提示，技术细节写日志 | `tests/test_relocator.py`（11 项）、`tests/test_missing_files_batch.py`（5 项）、`tests/test_main_window_phase7.py`（8 项）、`tests/test_error_messages.py`（11 项） |

额外交付：

- 搜索词支持空格分隔的 **AND** 语义（如 `马克思 资本`），每个词可命中节点名或任意 PDF 路径。
- 同时兼容新数据库（`ensure_ascii=False`）和旧数据库（`\u8d44\u672c` 形式）中的中文 PDF 路径。
- 结果按“名称命中优先”排序；名称与 PDF 同时命中时在第二列显示来源。
- 不可达节点（只存在于循环中的节点）也能被搜索到，位置列显示“（没有可达位置）”。
- 批量重新定位支持递归扫描、同名文件路径后缀择优、歧义跳过、逐条错误隔离，
  只改数据库引用，不移动/删除磁盘文件（plan.md §40）。
- 窗口位置完全落到屏幕外时自动居中到主屏，避免换显示器后窗口找不回来。

---

## 二、关键设计决定

1. **搜索词交给 SQLite，结果分类交给 Python**
   `Database.search_nodes()` 用参数化 `LIKE ... ESCAPE '\'` 先筛选候选节点；
   `services/search.py` 再做大小写不敏感的精确分类、PDF 文件名提取和位置组装。
   这样既避免把整库加载进内存，也能正确处理用户输入的 `%` / `_`（按字面量匹配）。

2. **一个节点只返回一条 hit，位置全部展开**
   多父级节点在结果中只出现一次，其下按 `get_node_paths()` 列出所有
   `根 > … > 节点` 面包屑。点击某个位置时调用 `_reveal_display_path()`，
   展开该路径并选中 **这个显示实例**，而不是随便选中另一个同名实例
   （plan.md §16 / §28）。

3. **搜索是同步的，但带防抖**
   本地 SQLite 查询足够快；`QTimer` 250 ms 防抖避免每个按键一次查询。
   没有引入线程池，行为可预测、测试稳定。结果上限默认 100、最大 500，
   超出时明确提示“只显示前 N 个节点”，不做静默截断。

4. **展开状态按“显示路径”保存，而不是节点 ID 集合**
   同一个节点可以在“马列”下展开、在“西欧哲学家”下折叠。若只保存节点 ID
   无法区分两个显示实例。配置中保存 `[[1], [1, 2], ...]`，恢复时按长度
   从父到子展开；最多 500 条，避免配置文件无限增长（plan.md §10）。

5. **窗口状态保持可读**
   `config.json` 的 `ui.window_width/height/x/y/window_maximized` 仍是普通整数，
   不写 Qt 的二进制 geometry blob（plan.md §33）。恢复时保留用户尺寸，
   只在窗口完全不可见时重新居中；最大化状态单独保存，关闭时记录
   `normalGeometry()`，因此取消最大化后大小仍然正确。

6. **批量重新定位只“计划”不直接写库**
   `services/relocator.py` 只扫描目录并产出 `RelinkPlan`（matched / ambiguous /
   not_found）。控制器再逐条走已有的 `relink_pdf()`，因此相对路径策略、
   `copy_to_books` 策略、重复引用检查全部复用 Phase 4 的唯一实现。
   同名文件有多个时优先用原存储路径的后缀匹配；仍有歧义就跳过并报告，
   绝不猜测用户想用哪个文件。

7. **日志负责技术细节，界面只显示用户语言**
   `utils/error_messages.describe_error()` 把 `database is locked`、只读数据库、
   权限不足、文件不存在、JSON 解析失败等翻译成中文提示并给出下一步建议；
   调用方用 `log_exception()` 把完整 traceback 写入日志（plan.md §39）。
   现有 `QMessageBox.warning/critical` 调用点保持原样，只替换消息文本，
   不改变既有测试容易注入的 UI 结构。

8. **测试与真实用户配置隔离**
   `tests/conftest.py` 的自动 fixture 把默认 `constants.CONFIG_PATH` 指向每个测试
   自己的临时目录。Phase 7 的窗口关闭会写配置，这个隔离保证测试不会改动
   仓库中的 `config.json`，也让“关闭后重开恢复状态”的测试可以复用临时配置。

---

## 三、文件清单

### 新增

```text
utils/settings_manager.py               # 窗口几何、展开路径、搜索栏可见性
utils/error_messages.py                 # 异常 -> 用户提示 / 技术细节
services/search.py                      # 搜索模型、匹配分类、全部位置
services/relocator.py                   # 批量同名 PDF 扫描与匹配计划
views/search_panel.py                   # 搜索结果树 + 面板
views/dialogs/search_dialog.py          # 独立搜索对话框
tests/test_settings_manager.py          # 12 项
tests/test_search_service.py            # 12 项
tests/test_relocator.py                 # 11 项
tests/test_error_messages.py            # 11 项
tests/test_logger.py                    # 5 项
tests/test_search_ui.py                 # 9 项
tests/test_main_window_phase7.py        # 8 项
tests/test_missing_files_batch.py       # 5 项
```

### 修改

```text
utils/constants.py                      # UI/日志/搜索/重定位常量
utils/config_manager.py                 # UI 新键、logging 段、None 默认值合并修复
utils/logger.py                         # 轮转文件日志、log_exception、shutdown、可配置级别
models/database.py                      # search_nodes()、LIKE 转义、旧 JSON 路径兼容
models/library.py                       # search_nodes() 业务入口
controllers/app_controller.py           # search_library / plan_missing_relocation / relink_missing_from_folder
views/main_window.py                    # 搜索框、结果 Dock、搜索对话框、几何/展开状态持久化、错误提示
views/dialogs/missing_files_dialog.py   # 批量重新定位按钮、递归选项、结果汇总
views/dialogs/pdf_management_dialog.py  # 友好错误提示
views/dialogs/icon_selector_dialog.py   # 友好错误提示
main.py                                 # 启动环境日志、完整 traceback、退出 flush
config.json                             # Phase 7 新配置键
tests/conftest.py                       # 测试默认配置隔离
_mds/plan.md                            # Phase 7 九项勾选
```

### 测试分布

| 文件 | 项数 | 说明 |
|---|---:|---|
| `tests/test_settings_manager.py` | 12 | 几何/展开路径/可见性/旧配置合并 |
| `tests/test_search_service.py` | 12 | 名称、PDF、多父级位置、AND、上限、转义、旧库兼容 |
| `tests/test_relocator.py` | 11 | 递归/非递归、歧义、后缀择优、控制器批量写入 |
| `tests/test_error_messages.py` | 11 | SQLite/文件/JSON/通用异常映射 |
| `tests/test_logger.py` | 5 | 文件写入、traceback、轮转参数、级别、重建 |
| `tests/test_search_ui.py` | 9 | 主窗口搜索、点击定位、清空、刷新、对话框 |
| `tests/test_main_window_phase7.py` | 8 | 几何/展开保存恢复、离屏修复、菜单快捷键 |
| `tests/test_missing_files_batch.py` | 5 | 全部/选中/部分匹配/错误/选项传递 |
| **新增合计** | **73** | |
| 既有测试 | 364 | 全部通过，无回归 |

---

## 四、验证方式

```powershell
# 项目根目录
D:\Anaconda\envs\pyside\python.exe -m pytest
```

本次实际执行结果：

```text
437 passed in 18.82s
```

GUI 冒烟使用真实 Windows 平台渲染，截图保存在 `logs/`（该目录被 `.gitignore`
忽略，属于本地验证产物）：

- `logs/phase7_demo/phase7_search.png`：搜索“马克思”，右侧结果 Dock 显示
  “1 个节点，共 2 个位置”，两条完整面包屑
  `经济政治 > 马列 > 马克思`、`经济政治 > 西欧哲学家 > 马克思`，
  树中对应实例带 `×2` 角标。
- `logs/phase7_demo/phase7_reopened.png`：关闭再打开后，窗口尺寸 1360×860、
  5 条展开分支（`[1] [6] [1,2] [1,5] [6,7]`）全部恢复，搜索 Dock 按上次状态显示。
- `logs/phase7_demo/phase7_missing_dialog.png`：缺失文件对话框出现
  “批量重新定位…”“包含子文件夹”等 Phase 7 按钮。
- `logs/phase7_demo/config.json`：可见 `expanded_paths`、`window_*`、
  `search_panel_visible` 等可读配置项。

> 环境备注：当前 DSH Windows 文件沙箱中，pytest 的 `tmp_path`（`mode=0o700`）
> 目录不可读写；本次沿用 `logs/run_pytest.py` 启动器把临时目录模式放宽到
> `0o755` 后运行。普通开发机直接使用上面的 `pytest` 命令即可。

---

## 五、已知边界

- 搜索使用 SQLite `LIKE` 子串匹配，不支持拼音、近似匹配、正则或标签搜索；
  `metadata.tags` 的扩展位置已预留，但 Phase 7 不解析标签。
- 每次搜索最多返回 100 个节点（可通过 `limit` 调到 500）；每个命中节点
  会列出全部位置。超大书库若需要全文/模糊搜索，后续应改用 FTS5 或索引缓存。
- 搜索是同步执行的。十万级节点且关键词极短时，输入防抖后仍可能有一次
  明显的查询停顿；需要时再引入后台查询。
- 批量重新定位按 **文件名**（大小写不敏感）匹配，不比较文件内容哈希；
  同名文件无法用原路径后缀区分时会标记为“同名文件有多个”并跳过，
  需用户逐条重新定位。
- 展开状态最多保存 500 条显示路径；更大的树只恢复前 500 条（按深度/路径排序）。
- 窗口状态只记录普通矩形与最大化标志，不记录多显示器编号；若保存位置
  完全不在当前屏幕内会自动居中。
- 日志轮转为 2 MB × 3 个文件；没有内置日志查看器，直接打开 `logs/` 下的文件即可。
- 搜索侧栏的可见性会保存，但搜索词不保存；重开程序后侧栏是空状态提示。

---

## 六、后续阶段衔接

- **Phase 8**：`annotation_handler` 可在现有 `metadata` 字典中保存 FDF 映射；
  搜索服务已经能按需增加 metadata 标签匹配而无需改 UI 结构。
- `SearchHit.node` 保留了完整 `Node` 数据，未来标签/作者字段可直接加入
  `match_label` 与结果列。
- `SettingsManager` 可继续扩展主题、字体、确认偏好等 UI 设置，写配置的方式
  与现有 `ConfigManager` 一致。
- `log_exception()` 与 `describe_error()` 可作为后续所有新对话框的统一错误入口。

---

*本报告依据 `_mds/plan.md`、`_mds/stage.md` 与 Phase 7 实际代码编写。*
