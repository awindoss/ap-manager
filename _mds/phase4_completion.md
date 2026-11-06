# Phase 4 完成报告：PDF 管理

> 完成日期：2026-10-31
> 代码基线：Phase 1 + 2 + 3 工作树
> 验证环境：Python 3.11.15 / PySide6 6.11.1 / pytest 9.1.1（Windows，offscreen 测试）
> 验证结果：**228 项测试全部通过**（Phase 3 基线 120 项 + 本阶段新增 108 项）

---

## 一、结论

`_mds/plan.md` 第 35 节 Phase 4 的 9 项检查全部完成，`_mds/stage.md` Phase 4 的
4.1 ~ 4.7 全部落地：

| stage.md 任务 | 实现 |
|---|---|
| 4.1 `path_manager` | 新增 `make_stored_path()`（相对/绝对/复制到 books）、`copy_into_books()`（内容哈希去重）、`describe_pdf(s)`、`pdf_path_key()`、`is_within_root()`、`relative_to_root()`；原有存在性检查保留 |
| 4.2 `pdf_launcher` | 新增 `PdfLauncher` / `PdfLaunchError` / `LaunchReport`；指定阅读器优先、否则 Windows `os.startfile`、macOS `open`、Linux `xdg-open`；阅读器参数支持字符串/列表；单文件与批量打开 |
| 4.3 `library` PDF 方法 | `get_pdf_list` / `set_pdf_list` / `add_pdf(s)` / `remove_pdf(s)` / `relink_pdf`，去重、保序、只改数据库不删文件 |
| 4.4 `pdf_management_dialog` | 多选列表、添加多个文件、移除、重新定位、打开选中/全部、`复制到 books/` 开关、缺失行红色警告与 tooltip |
| 4.5 `pdf_selector_dialog` | 多 PDF 时选择打开；缺失项标红且不可打开，双击有效项直接打开 |
| 4.6 右键菜单 | 新增「管理 PDF… / 打开 PDF / 打开全部 PDF / 重新定位缺失 PDF…」；编辑菜单同步提供入口与快捷键 |
| 4.7 文件缺失检测 | 树图标警告点在 Phase 3 已实现；本阶段新增「工具 → 文件检查…」与「重新定位缺失 PDF…」全库工作流 |

额外交付：

- `utils/config_manager.py`：原子写入、损坏配置自动备份、保留未知配置节；
  `pdf_reader.path / args` 与 `library.database_path` 均可读取，`AppController`
  现在会真正使用配置中的数据库路径。
- 「设置 → PDF 阅读器…」对话框，可指定可执行文件或恢复系统默认。
- 缺失文件列表支持多行查看、单条重新定位、定位到节点并直接打开 PDF 管理器。
- 全部 PDF 打开失败时汇总提示（最多展示 5 条明细），不会因一个文件失败中断其余文件。

未改动数据库结构，未改动 nodes + edges 图语义；`data/library.db` 仍为空库。

---

## 二、关键设计决定

1. **路径策略（写入侧）**
   - 文件位于应用根目录内 → 存相对 POSIX 路径（`books/a.pdf`）；
   - 位于根目录外 → 存绝对路径（该条目失去整体迁移能力，但尊重用户「不复制」的选择）；
   - 勾选「复制到 books/」→ 先复制再存相对路径。同名不同内容用
     `<stem>_<sha256[:8]>.pdf` 区分；同名同内容复用已有副本，不产生重复文件。
   - 复制与比较均分块流式计算，不把整本 PDF 读入内存。

2. **缺失文件只提示、不删除引用**
   `inspect_pdfs()` / `find_missing_pdfs()` 只读扫描；重新定位只替换路径，
   保持其在列表中的位置（plan.md §22）。移除 PDF 也只删除数据库引用，
   磁盘文件始终保留（plan.md §40）。

3. **多父级一致性**
   PDF 列表属于 `node_id` 而不是某个显示实例。PDF 管理器修改后调用
   `TreeModel.notify_node_changed()`，同一节点的所有树实例一起重绘；
   若节点只存在于不可达环中则退回 `refresh()`。
   这样修改 PDF 不会触发 `modelReset`，展开状态与选中项保持不变。

4. **读取器配置**
   `config.json -> pdf_reader.path` 为空时使用平台默认阅读器；非空时必须是已存在
   的文件（避免拼写错误静默失效）。相对路径按应用根目录解析后存绝对路径。
   `pdf_reader.args` 支持字符串（`shlex` 解析）或列表，文件路径始终放在参数末尾。

5. **启动失败不崩溃**
   文件不存在、阅读器不存在、`Popen`/`os.startfile` 失败都转换为
   `PdfLaunchError`，由 UI 弹出可理解的中文提示并写日志（plan.md §39）。

6. **对话框即时生效**
   PDF 管理器与缺失文件对话框的每次操作立即通过控制器写库，关闭按钮只关闭窗口。
   这样列表、数据库、树视图不会出现「取消后状态不一致」；代价是操作后关闭窗口
   仍可能留下已复制到 `books/` 的文件，但不会产生任何错误引用。

7. **添加时的存在性校验**
   通过 UI/控制器添加 PDF 时要求源文件当前存在且扩展名为 `.pdf`；因此本阶段
   不能借添加流程写入不存在的引用。Phase 6 导入器需要「缺失 PDF 仅警告」的语义，
   应直接调用 `LibraryService.add_pdfs()`（它不检查磁盘），而不是
   `AppController.add_pdfs()`。

8. **文件检查入口**
   「文件检查」在无缺失时给出统计信息；有缺失时询问是否进入重新定位列表。
   「重新定位缺失 PDF」直接打开全库缺失列表，支持逐条重新定位、定位节点。

---

## 三、文件清单

### 新增

```text
utils/config_manager.py
services/pdf_launcher.py
views/dialogs/pdf_management_dialog.py
views/dialogs/pdf_selector_dialog.py
views/dialogs/missing_files_dialog.py
views/dialogs/settings_dialog.py

tests/test_config_manager.py
tests/test_pdf_launcher.py
tests/test_library_pdfs.py
tests/test_controller_pdfs.py
tests/test_pdf_dialogs.py
```

### 修改

```text
services/path_manager.py          # 存储/复制/描述/路径键
models/library.py                 # PDF 引用增删改查与重新定位
controllers/app_controller.py     # PDF 入口、文件检查、阅读器设置、配置化数据库路径
views/main_window.py              # 菜单、右键菜单、双击、文件检查、设置
views/dialogs/node_properties_dialog.py  # PDF 只读区提示指向 PDF 管理器
utils/constants.py                # PDF 过滤器/路径长度/复制块大小/命名规则
config.json                       # pdf_reader.args 模板
_mds/plan.md                      # Phase 4 九项勾选
```

### 测试分布

| 文件 | 项数 | 说明 |
|---|---:|---|
| `tests/test_path_manager.py` | 16 | 原有 6 项 + Phase 4 存储/复制/描述 10 项 |
| `tests/test_config_manager.py` | 7 | 默认值、合并、持久化、损坏备份 |
| `tests/test_pdf_launcher.py` | 17 | 命令构造、三平台默认阅读器、失败路径、批量打开 |
| `tests/test_library_pdfs.py` | 13 | 添加/去重/删除/重定位/多父级共享 |
| `tests/test_controller_pdfs.py` | 19 | 路径转换、复制、部分失败、打开、文件检查、阅读器设置 |
| `tests/test_pdf_dialogs.py` | 30 | 管理/选择/设置/缺失文件对话框 |
| `tests/test_main_window.py` | 31 | 原 19 项 + PDF 菜单/双击/文件检查/设置 12 项 |
| 其余既有测试 | 95 | 未回归 |

---

## 四、验证方式

```powershell
# 项目根目录
D:\Anaconda\envs\pyside\python.exe -m pytest
```

本次实际执行结果：

```text
228 passed in 92.56s
```

真实 GUI（非 offscreen）复核通过，截图保存在 `logs/`（该目录被 `.gitignore` 忽略）：

- `logs/phase4_main_window.png`：多父级「资本论」两处显示 `×2`、状态栏「缺失 PDF 1」、
  菜单栏含 文件/编辑/查看/工具/设置。
- `logs/phase4_pdf_management.png`：3 个 PDF，其中缺失项红色并带 ⚠；
  添加/复制/移除/重新定位/打开按钮与「关闭」。
- `logs/phase4_pdf_selector.png`：多 PDF 选择，缺失项标红。
- `logs/phase4_settings.png`：阅读器设置（留空 = 系统默认）。
- `logs/phase4_missing_files.png`：全库缺失列表与重新定位入口。

> 环境备注：当前 DSH Windows 文件沙箱中，pytest 的 `tmp_path`（`mode=0o700`）
> 目录不可列举。本次沿用 Phase 3 的本地启动器放宽目录模式后运行，启动器未纳入
> 版本库；普通开发机直接使用上面的命令即可。

> 版本库备注：后续已补提交为 `238e604`（Phase 4 complete）。

---

## 五、后续阶段衔接

- **Phase 5**：`attach_nodes` / `detach_nodes` 后调用 `model.refresh()` 重建父级计数；
  PDF 管理器已经演示了「修改节点 → `notify_node_changed()` 保持展开状态」的路径。
- **Phase 6**：导出时可复用 `path_manager.relative_to_root()` / `normalize_stored_path()`；
  导入缺失 PDF 需直接走 `LibraryService.add_pdfs()`（见设计决定 7）；
  图标与 PDF 的 `books/`、`icons/` 复制策略一致。
- **Phase 7**：`ConfigManager` 已具备通用 `get/set` 与原子保存，`settings_manager`
  可在此基础上增加窗口几何与展开状态；`inspect_pdfs()` 可作为批量重新定位的数据源。

---

*本报告依据 `_mds/plan.md`、`_mds/stage.md` 与 Phase 4 实际代码编写。*
