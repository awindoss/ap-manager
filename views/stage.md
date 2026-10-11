# PDF 层级书籍收藏管理器 — 开发阶段细化文档 (stage.md)

本文件基于 plan.md 的 Phase 1 ~ Phase 8，将每个阶段拆解到具体文件、类、函数及验收标准。目的是为开发者提供清晰的实现路径，避免重复造轮或遗漏关键模块。

## 前置准备

- 创建项目根目录 ap_manager/，按 plan.md 第 5 节建立子目录。
- 初始化 Git 仓库，创建 requirements.txt（内容：PySide6>=6.5.0）。
- 创建 config.json 模板（内容见 plan.md 第 33 节）。
- 创建空的 data/library.db（SQLite 文件）。

# Phase 1：数据库与核心模型（约 2~3 天）

目标：完成数据层的全部 CRUD 及循环检测，不依赖 GUI。

## 涉及文件

```text
models/
├── database.py
├── node.py
├── edge.py
└── library.py

utils/
├── constants.py
└── logger.py

tests/（新建）
└── test_database.py

```

## 具体任务

### 1.1`utils/constants.py`

- 定义数据库路径常量 DB_PATH = "data/library.db"

- 定义 JSON 版本常量 LIBRARY_FORMAT_VERSION = "0.1"

### 1.2`utils/logger.py`

- 实现简单日志函数 log_info(msg), log_error(msg)，输出到控制台或文件（可选）。

### 1.3`models/node.py`

- 定义 Node dataclass：

```python
@dataclass
class Node:
  id: Optional[int]
  name: str
  pdf_paths: List[str] = field(default_factory=list)
  icon: str = ""
  style_bold: bool = False
  style_color: str = "#000000"
  metadata: dict = field(default_factory=dict)
  created_time: Optional[str] = None
  updated_time: Optional[str] = None
```

### 1.4`models/edge.py`

- 定义 Edge dataclass：

```text
@dataclass
class Edge:
    id: Optional[int]
    parent_id: int
    child_id: int
    sort_order: int = 0
```

### 1.5`models/database.py`

- 实现 Database 类，负责连接和建表：

  - __init__(db_path)
  - connect() → 返回 sqlite3.Connection
  - init_tables() → 执行 CREATE TABLE IF NOT EXISTS nodes 和 edges（含索引，见 plan 第 37 节）
- 实现节点 CRUD：

  - add_node(node: Node) -> int（返回新 ID）
  - get_node(node_id: int) -> Optional[Node]
  - update_node(node_id: int, **kwargs)（更新 name, pdf_paths, icon, style_bold, style_color, metadata）
  - delete_node(node_id: int)（同时删除所有关联 edges，用事务）
- 实现边 CRUD：

  - add_edge(parent_id: int, child_id: int, sort_order: int = 0) -> int
  - delete_edge(parent_id: int, child_id: int)（或按 edge_id）
  - get_children(parent_id: int) -> List[int]（返回 child_id 列表，按 sort_order 排序）
  - get_parents(child_id: int) -> List[int]（返回 parent_id 列表）
  - get_root_nodes() -> List[int]（没有父节点的节点 ID）
  - get_all_positions(node_id: int) -> List[List[int]]（返回从根到该节点的所有路径，用于 UI 定位）
- 辅助函数：

  - would_create_cycle(parent_id: int, child_id: int) -> bool（通过递归查询父节点，检测是否有路径 child → ... → parent）

### 1.6`models/library.py`（业务层）

- 定义 LibraryService 类，接收 Database 实例：

  - create_node(name, **kwargs) -> Node
  - attach_node(parent_id, child_id) → 调用 db.add_edge，先检查循环
  - detach_node(parent_id, child_id) → 删除边，若节点无任何父级且非根（根可无父级），可选择保留或警告
  - move_node(parent_id, child_id, new_parent_id) → 先删除旧边，再添加新边（需确保不循环）
  - delete_node_completely(node_id) → 删除节点及其所有边（事务）
  - get_node_children(node_id) → 返回 List[Node]
  - get_node_parents(node_id) → 返回 List[Node]
  - get_all_roots() → List[Node]
  - get_all_positions(node_id) → 返回 List[List[Node]]（路径节点列表）

### 1.7 单元测试`tests/test_database.py`

- 使用 unittest 或 pytest，测试：

  - 增删改节点
  - 添加边、查询子/父
  - 循环检测（应返回 True/False）
  - 删除节点级联删除边
  - 根节点查询
  - 多父级场景（如 A→X, B→X）

验收标准：

- 所有单元测试通过。
- 能手动执行 Python 脚本，创建数据库并插入样例数据，用 sqlite3 命令行验证表结构及数据。

# Phase 2：QTreeView 基础显示（约 2~3 天）

目标：将数据库图结构投影到 QTreeView，并正确处理多父级及循环保护。

## 涉及文件

```text
views/
├── main_window.py
└── tree_model.py  (新增)

controllers/
└── app_controller.py

models/
└── library.py  (可能微调)
```
## 具体任务

### 2.1`models/library.py`补充方法

- 确保 get_node_children(node_id) 返回按 sort_order 排序的子节点列表。

### 2.2`views/tree_model.py`

- 定义 TreeItem 内部类（或简单 dataclass）：

python复制下载

```text
class TreeItem:
    node_id: int
    parent_item: Optional['TreeItem']
    children: List['TreeItem']
    display_path: Tuple[int, ...]   # 用于路径去重
```

- 实现 TreeModel 继承 QAbstractItemModel：
  - __init__(library_service)，存储根 items 列表。
  - load_roots() → 调用 lib.get_all_roots()，为每个根创建 TreeItem，递归构建子树。
  - build_subtree(parent_item, current_path_set) 递归：

    - 对每个子节点，检查 child_id in current_path_set，若在则跳过并记录警告（循环），否则创建 TreeItem。
  - 重写 index(row, column, parent_index)、parent(index)、rowCount(parent_index)、columnCount()、data(index, role)。
  - data 返回：Qt.DisplayRole → 节点名称（可拼接角标），Qt.DecorationRole → 图标（待 Phase 3），Qt.FontRole（待 Phase 3）。
  - flags 返回可编辑标志（暂不实现编辑）。
  - 提供 refresh() 方法，清除现有 items 并重新构建全部（初期简单实现）。

### 2.3`views/main_window.py`

- 创建 MainWindow 继承 QMainWindow。
- 初始化时创建 LibraryService 和 Database，并传入 TreeModel。
- 创建 QTreeView，设置 model。
- 连接双击信号 doubleClicked：

  - 获取当前 TreeItem 的 node_id。
  - 若节点无子节点且至少有 PDF，则弹出 PDF 选择（暂不实现，Phase 4）。
  - 否则展开/折叠（默认行为）。

### 2.4`controllers/app_controller.py`

- 简单封装，连接界面与业务逻辑，初期可仅作为中转。

验收标准：

- 从数据库加载根节点，正确显示多父级结构（如 A→X, B→X，X 出现两次）。
- 双击展开/折叠正常。
- 若出现循环，日志有警告，界面不崩溃。

# Phase 3：节点编辑与视觉自定义（约 2 天）

目标：支持节点名称、图标（内置+自定义）、加粗、颜色，并显示多父级角标。

## 涉及文件

text复制下载

```text
views/
├── tree_model.py
├── delegates/
│   └── tree_delegate.py
├── dialogs/
│   ├── add_node_dialog.py
│   ├── node_properties_dialog.py
│   └── icon_selector_dialog.py

models/
├── database.py
└── library.py

utils/
└── icon_utils.py (新增)
```## 具体任务

### 3.1`utils/icon_utils.py`

- 提供 get_icon_path(icon_str)：判断是内置 emoji 还是自定义图片路径（相对路径）。
- 提供 load_icon(icon_str, size=16) 返回 QIcon 或 QPixmap（处理 .png/.ico/.svg）。

### 3.2`views/delegates/tree_delegate.py`

- 继承 QStyledItemDelegate，重写 paint：

  - 从 model 获取 node 数据，绘制图标（用 icon_utils）、名称。
  - 如果 style_bold 为 True，设置粗体。
  - 使用 style_color 设置文本颜色。
  - 若节点有多个父级（len(get_parents(node_id)) > 1），在名称后绘制角标（如 “×2” 小字）。
- 重写 sizeHint 适应图标和角标。

### 3.3`views/tree_model.py`增强

- 在 data 中返回 Qt.FontRole 和 Qt.ForegroundRole，基于节点属性。

### 3.4`views/dialogs/add_node_dialog.py`

- 对话框：输入节点名称，可选图标（内置选择器），是否加粗，颜色选择。
- 确认后调用 library_service.create_node，然后刷新模型。

### 3.5`views/dialogs/node_properties_dialog.py`

- 编辑现有节点属性：名称、图标、加粗、颜色。
- 也显示当前 PDF 列表（但编辑 PDF 另做，Phase 4）。

### 3.6`views/dialogs/icon_selector_dialog.py`

- 显示内置 emoji 列表（硬编码），并提供“浏览自定义图片”按钮，选择文件后复制到 icons/ 目录，存储相对路径。

### 3.7 右键菜单（暂在 main_window 中实现）

- 连接 customContextMenuRequested，弹出菜单：

  - “新建子节点” → 打开 AddNodeDialog
  - “编辑属性” → NodePropertiesDialog
  - “设置样式” → 可直接调属性对话框
- 刷新模型。

验收标准：

- 新建节点可指定图标/加粗/颜色。
- 编辑后树视图立即更新。
- 多父级节点显示角标（如 ×2）。
- 自定义图片图标正常显示。

# Phase 4：PDF 管理（约 2~3 天）

目标：节点可挂载多个 PDF，打开 PDF（调用外部阅读器），处理缺失文件。

## 涉及文件

text复制下载

```text
services/
├── pdf_launcher.py
└── path_manager.py

views/
├── dialogs/
│   ├── pdf_management_dialog.py
│   └── pdf_selector_dialog.py
├── main_window.py
└── tree_model.py (无修改)

models/
├── database.py (更新节点 pdf_paths)
└── library.py (增加 PDF 操作方法)

controllers/
└── app_controller.py (增加 PDF 入口)
```## 具体任务

### 4.1`services/path_manager.py`

- 提供 normalize_path(path)，相对路径转绝对（基于当前工作目录或配置的书籍根目录）。
- is_pdf_exists(relative_path) 检查文件是否存在。
- resolve_pdf_path(relative_path) 返回绝对路径，若不存在返回 None。

### 4.2`services/pdf_launcher.py`

- 实现 launch_pdf(pdf_abs_path, reader_path=None)：

  - 若 reader_path 非空，用 subprocess.Popen([reader_path, pdf_abs_path])
  - 否则按平台：Windows os.startfile, macOS open, Linux xdg-open
- 读取 config.json 中的 pdf_reader.path。

### 4.3`models/library.py`增加方法

- add_pdf(node_id, pdf_relative_path) → 添加至 node.pdf_paths（去重）
- remove_pdf(node_id, pdf_relative_path)
- get_pdf_list(node_id) → 返回相对路径列表
- set_pdf_list(node_id, list)

### 4.4`views/dialogs/pdf_management_dialog.py`

- 显示当前节点的所有 PDF 列表（路径）。
- 按钮：“添加文件”（打开文件选择器，支持多选）、“移除选中”、“定位文件”。
- 添加时，询问是否复制到 books/ 目录，或直接记录相对路径（由用户选择）。
- 确认后调用 library_service.add_pdf 或 set_pdf_list。

### 4.5`views/dialogs/pdf_selector_dialog.py`

- 当节点有多个 PDF 且用户双击打开时，弹出列表让用户选择要打开的 PDF。
- 选择后调用 pdf_launcher.launch_pdf。

### 4.6 右键菜单增强

- 添加“管理 PDF” → 打开 PdfManagementDialog
- 添加“打开全部 PDF” → 打开全部（逐个启动）

### 4.7 文件缺失检测

- 在 TreeModel 的 data 中，若节点有 PDF 且任意一个文件不存在，则在图标或文本上添加警告标记（如 ⚠️）。
- 在 main_window 中，可定期或启动时检查所有 PDF，汇总缺失文件列表。

验收标准：

- 可添加多个 PDF，保存路径相对。
- 双击打开正常（单个直接打开，多个弹出选择）。
- 缺失文件显示警告，并可通过“定位文件”更新路径。

# Phase 5：多父级高级交互（约 2 天）

目标：实现“查看所有位置”、“从当前父级移除”、“彻底删除”、“关联到其他位置”、“移动”及拖拽。

## 涉及文件

text复制下载

```text
views/
├── dialogs/
│   ├── choose_parent_dialog.py
│   └── node_positions_dialog.py
├── main_window.py (拖拽事件)
└── tree_model.py (增加移动/关联方法)

controllers/
└── app_controller.py
```## 具体任务

### 5.1`views/dialogs/choose_parent_dialog.py`

- 显示所有可选的父节点（除自身及其后代，防止循环），以树形展示（可用 QTreeView + 临时模型）。
- 用户选择一个或多个父级，返回 node_id 列表。

### 5.2`views/dialogs/node_positions_dialog.py`

- 显示选中节点的所有路径（从根到该节点的完整链）。
- 每个路径可点击，点击后主窗口定位到该位置（通过展开 treeview 并选中对应 item）。

### 5.3 右键菜单实现

- “关联到其他位置” → 打开 ChooseParentDialog，选择父级后调用 library.attach_node
- “查看所有位置” → NodePositionsDialog
- “从当前父级移除” → 删除当前边（需知道当前选中项的父节点），调用 library.detach_node
- “彻底删除节点” → 确认后调用 library.delete_node_completely

### 5.4 拖拽支持

- 在 QTreeView 中启用拖放：

  - setDragEnabled(True)，setAcceptDrops(True)，setDropIndicatorShown(True)。
  - 重写 dragMoveEvent 和 dropEvent。
  - 拖拽源：选中节点（可多选）。
  - 拖放目标：另一个节点（作为父级）。
  - 弹出菜单询问“关联到此”还是“移动到此”。
- 实现“移动” = 删除原边 + 添加新边（需检查循环）。

### 5.5 循环检测及时反馈

- 所有新增/移动操作前调用 would_create_cycle，若为真则弹出错误提示。

验收标准：

- 关联、移除、彻底删除操作正确，边和节点状态符合预期。
- “查看所有位置”正确显示所有路径并能定位。
- 拖拽创建/移动关系，循环被阻止。

# Phase 6：导入与导出（约 2~3 天）

目标：完整 JSON 导入/导出，支持相对路径和外部 ID 映射。

## 涉及文件

text复制下载

```text
services/
├── exporter.py
└── importer.py

views/
├── dialogs/
│   └── import_export_dialog.py (或直接菜单)
└── main_window.py

models/
├── database.py (需支持批量插入)
└── library.py (辅助批量)

utils/
└── json_utils.py
```## 具体任务

### 6.1`services/exporter.py`

- export_library(library_service, export_dir)：

  - 创建 export_dir 目录。
  - 收集所有节点和边，构建 JSON 对象（格式见 plan 第 23.2）。
  - 为每个节点的 PDF 路径，转换为相对于 export_dir 的路径（若文件在 books/ 等子目录中）。
  - 若节点有自定义图标，需将图标文件复制到导出目录的 icons/ 下，并调整路径。
  - 写入 library.json。
- 返回导出成功/失败。

### 6.2`services/importer.py`

- import_library(db, json_path)：

  - 读取 JSON，校验版本。
  - 构建 external_id → local_id 映射字典。
  - 遍历 nodes，插入数据库（不指定 id，让 SQLite 自动生成），记录映射。
  - 遍历 edges，用映射后的 ID 调用 db.add_edge（需再次循环检测，但导入时已知无循环，仍可检查）。
  - 处理 PDF 路径：将 JSON 中的相对路径转换为相对于 json_path 所在目录的绝对路径，然后存储为相对路径（相对于当前应用的工作目录或配置的书籍根目录）。
  - 若文件不存在，记录警告但不中断。
- 整体事务，失败回滚。

### 6.3`utils/json_utils.py`

- 提供 validate_json_schema(data) 基本校验。

### 6.4 UI 集成

- 主菜单“导入图书馆” → 选择 JSON 文件 → 调用 importer，成功后刷新模型。
- “导出图书馆” → 选择目标文件夹 → 调用 exporter。

验收标准：

- 导出后，可复制到另一目录，导入后结构与原数据库一致，多父级保留。
- PDF 路径重新映射正确（若文件存在）。
- 导入时缺失文件仅警告，不中断。

# Phase 7：搜索与体验优化（约 2 天）

目标：搜索节点/PDF，定位到所有位置；记忆窗口状态；日志完善。

## 涉及文件

text复制下载

```text
views/
├── dialogs/
│   └── search_dialog.py
├── main_window.py (添加搜索框)
└── tree_model.py (增加查找接口)

controllers/
└── app_controller.py (搜索方法)

utils/
└── settings_manager.py (新增)
```## 具体任务

### 7.1`utils/settings_manager.py`

- 读写 config.json，包括窗口位置、大小、展开状态（存储为节点 ID 列表或路径）。
- 提供 save_window_geometry(geometry), load_window_geometry(), save_expanded_nodes(expanded_ids), load_expanded_nodes()。

### 7.2 搜索功能

- 在 main_window 添加 QLineEdit 搜索框。
- 输入时触发搜索（延迟过滤）。
- 搜索范围：节点名称、PDF 文件名（基于路径），以及未来 metadata 中的标签（暂不）。
- 搜索结果展示在一个弹出对话框或侧边栏，显示匹配节点及其所有位置路径。
- 点击结果，定位到树中对应位置（展开路径，选中 item）。

### 7.3 日志系统

- 完善 logger.py，输出到文件 logs/ 目录，记录操作和错误。

### 7.4 优化

- 窗口状态记忆。
- 展开状态记忆（可存储展开的节点 ID 集）。
- 错误提示更友好（使用 QMessageBox）。

验收标准：

- 搜索能准确找到节点和 PDF。
- 重启软件后窗口位置、展开状态恢复。
- 日志文件有记录。

# Phase 8：FDF / 注释扩展（约 1~2 天，可选）

目标：预留注释管理接口，但第一版可不实现完整功能，仅提供占位。

## 涉及文件

text复制下载

```text
services/
└── annotation_handler.py

models/
├── database.py (可能扩展表)
└── node.py (metadata 已预留)

views/
├── dialogs/
│   └── annotation_dialog.py
└── main_window.py (菜单入口)
```## 具体任务

### 8.1`services/annotation_handler.py`

- 定义 Annotation 数据类，及 save_annotation(node_id, pdf_path, fdf_path)、load_annotations(node_id) 等方法。
- 未来可扩展 PDFLauncher 传递 FDF 参数。

### 8.2 数据库扩展（可选）

- 可创建 annotations 表（见 plan 第 30 节），但 Phase 8 也可以只使用 metadata 存储。

### 8.3 UI 入口

- 在节点右键菜单加“管理注释”，打开对话框，允许关联 FDF 文件。
- 仅显示路径，不实现实际注释同步（需外部阅读器支持）。

验收标准：

- 可添加、查看注释文件路径，存储于数据库。
- 不影响核心功能。

## 附录：各阶段依赖关系

text复制下载

```text
Phase 1 (数据层) → Phase 2 (树视图) → Phase 3 (样式) → Phase 4 (PDF)
                                                  ↘ Phase 5 (多父级交互)
Phase 6 (导入导出) 依赖于 Phase 1~5 全部
Phase 7 (搜索优化) 依赖于 Phase 2~5
Phase 8 (注释) 可独立于 Phase 6,7，但建议在 Phase 4 之后
```## 整体验收清单（最终）

- □所有 Phase 功能完整。
- □多父级展示正确，循环被阻止。
- □PDF 打开、缺失检测、重新定位正常。
- □导入导出无损。
- □搜索快速，定位准确。
- □窗口状态保存。
- □日志文件记录。
- □整体无崩溃，错误提示友好。

此 stage.md 为开发指导性文档，可根据实际情况调整优先级和实现细节。建议每个 Phase 完成后进行代码审查并更新文档。