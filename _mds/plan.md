# PDF 层级书籍收藏管理器 — 最终开发规划

> 版本：3.0  
> 定位：本地 PDF 书籍收藏、分类、关联与启动管理工具  
> 核心原则：**数据与分类解耦、分类允许多重归属、界面保持树状易用性、文件路径可迁移、为未来注释/FDF 扩展留出空间。**

---

## 1. 项目概述

本软件是一款基于 Python + PySide6 的本地 PDF 书籍收藏管理器。

它**不是 PDF 阅读器，也不负责解析 PDF 正文内容**。软件的核心职责是：

1. 管理用户收藏的 PDF 文件；
2. 用灵活的层级结构组织书籍；
3. 允许同一个“库”或“容器”同时出现在多个分类位置；
4. 允许用户自定义节点的名称、图标和视觉样式；
5. 调用用户选择的第三方 PDF 阅读器打开文件；
6. 支持将整个书籍分类系统导出/导入，并使用相对路径实现迁移；
7. 为未来的 FDF/PDF 注释管理、标签、搜索等功能保留扩展接口。

软件的核心不是一个固定的“文件夹模拟器”，而是一个：

> **以 PDF 为内容，以节点为组织对象，以多父级关系构成分类网络，再以树形界面向用户展示的本地知识型书籍管理器。**

---

# 2. 核心概念模型

## 2.1 四级语义

用户习惯上可以将自己的书籍组织为四类层次：

**图书馆 → 书架 → 库 → 容器**

例如：

```text
图书馆：经济政治
├── 书架：马列
│   ├── 库：马克思
│   │   ├── 容器：资本论
│   │   │   ├── 资本论 第一卷.pdf
│   │   │   ├── 资本论 第二卷.pdf
│   │   │   └── 资本论 第三卷.pdf
│   │   └── 容器：政治经济学批判.pdf
│   │
│   └── 库：恩格斯
│       └── 容器：社会主义从空想到科学的发展
│
└── 书架：西欧哲学家
    └── 库：马克思
```

但软件**不强制用户必须使用四层**。

用户可以根据书籍数量与个人习惯自由使用：

```text
书架
└── 容器
```

也可以：

```text
图书馆
└── 书架
    └── 库
        └── 容器
```

甚至允许：

```text
图书馆
└── 库
    └── 容器
```

因此，“图书馆 / 书架 / 库 / 容器”主要是**用户认知层面的语义角色**，而不是数据库中的四种不同实体类型。

---

# 3. 从树结构升级为多父级图结构

## 3.1 为什么不能使用单一 parent_id

最初的设计采用：

```text
node
 └── parent_id
```

这种结构只能表示：

> 一个节点只有一个父节点。

但实际需求中存在：

```text
书架：马列
└── 库：马克思

书架：西欧哲学家
└── 库：马克思
```

这里两个“马克思”不是两个不同的实体，而是：

> **同一个“马克思”节点被两个分类位置引用。**

同样：

```text
库：马克思
└── 容器：政治经济学批判

书架：正在阅读
└── 库：政治
    └── 容器：政治经济学批判
```

同一个“政治经济学批判”容器也可能同时属于多个分类。

因此，底层模型必须从：

> **单父级树**

升级为：

> **多父级有向图（实际运行时要求保持无环）。**

---

## 3.2 节点与关系分离

核心原则：

> `nodes` 保存“节点是什么”，`edges` 保存“节点在哪里”。

一个节点自身只有一份数据，但可以通过多个 `edges` 出现在不同位置。

逻辑示意：

```text
                 ┌── 马列 ──────────┐
                 │                  │
经济政治 ────────┤                  ├── 马克思
                 │                  │
                 └── 西欧哲学家 ────┘


马克思 ──────────┐
                 ├── 政治经济学批判
正在阅读 ── 政治 ┘
```

数据库只需要保存一个“马克思”和一个“政治经济学批判”。

---

# 4. 技术栈

| 层级 | 技术 | 用途 |
|---|---|---|
| GUI | PySide6 / Qt | 主界面、树视图、菜单、对话框 |
| 树视图 | QTreeView | 展示多父级图在 UI 中的树状投影 |
| 数据模型 | QAbstractItemModel（推荐） | 将数据库图结构映射成 Qt Model |
| 数据库 | sqlite3 | 本地单文件数据库 |
| 数据类 | Python dataclass | 节点、关系、配置等对象封装 |
| JSON | 标准 json | 导入/导出图书馆 |
| 路径 | pathlib | 跨平台路径处理 |
| PDF 启动 | subprocess / os.startfile / open / xdg-open | 调用第三方 PDF 阅读器 |
| 配置 | JSON | 阅读器路径、界面状态、用户偏好 |
| 打包 | PyInstaller | Windows `.exe` / macOS `.app` 等 |

原则上尽量使用 Python 标准库和 Qt 自带能力，避免不必要的第三方依赖。

---

# 5. 推荐项目结构

```text
ap_manager/
│
├── main.py                         # 程序入口
├── config.json                     # 用户配置
├── requirements.txt
├── README.md
├── plan.md
│
├── data/
│   └── library.db                 # SQLite 数据库
│
├── books/                          # 可选：软件管理的 PDF 文件目录
├── icons/                          # 可选：用户导入的自定义图标
│
├── models/
│   ├── __init__.py
│   ├── database.py                # 数据库连接、建表与 CRUD
│   ├── node.py                    # 节点数据模型
│   ├── edge.py                    # 关系数据模型
│   └── library.py                 # 图书馆/图结构业务模型
│
├── views/
│   ├── __init__.py
│   ├── main_window.py             # 主窗口
│   │
│   ├── dialogs/
│   │   ├── add_node_dialog.py
│   │   ├── node_properties_dialog.py
│   │   ├── choose_parent_dialog.py
│   │   ├── locate_file_dialog.py
│   │   └── settings_dialog.py
│   │
│   └── delegates/
│       └── tree_delegate.py       # 节点自定义绘制
│
├── controllers/
│   ├── __init__.py
│   └── app_controller.py
│
├── services/
│   ├── pdf_launcher.py
│   ├── exporter.py
│   ├── importer.py
│   ├── path_manager.py
│   └── annotation_handler.py      # 未来 FDF 扩展接口
│
└── utils/
    ├── constants.py
    ├── json_utils.py
    └── logger.py
```

---

# 6. 数据库设计

## 6.1 nodes：节点自身属性

```sql
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL,

    -- JSON 数组，保存该节点直接挂载的 PDF
    pdf_paths TEXT DEFAULT '[]',

    -- Emoji / 内置图标名称 / 相对图片路径
    icon TEXT,

    -- 基础视觉样式
    style_bold INTEGER NOT NULL DEFAULT 0,
    style_color TEXT DEFAULT '#000000',

    -- 为未来扩展保留
    metadata TEXT DEFAULT '{}',

    created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

说明：

- `id` 是全局唯一节点 ID；
- `name` 是节点名称；
- `pdf_paths` 保存节点直接拥有/挂载的 PDF；
- `icon` 保存图标信息；
- `style_bold` 控制是否加粗；
- `style_color` 保存字体颜色；
- `metadata` 为未来功能提供扩展空间。

---

## 6.2 edges：节点之间的父子关系

```sql
CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    parent_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL,

    -- 同一父级下的显示顺序
    sort_order INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY (parent_id)
        REFERENCES nodes(id)
        ON DELETE CASCADE,

    FOREIGN KEY (child_id)
        REFERENCES nodes(id)
        ON DELETE CASCADE,

    UNIQUE(parent_id, child_id)
);
```

这张表是整个系统支持“同一节点多处出现”的关键。

例如：

```text
(n1, n2) = 经济政治 → 马列
(n1, n3) = 经济政治 → 西欧哲学家
(n2, n4) = 马列 → 马克思
(n3, n4) = 西欧哲学家 → 马克思
```

此时 `n4` 只有一份“马克思”数据，但拥有两个父级。

---

# 7. 图结构规则

## 7.1 UI 使用树，数据库使用图

数据库真实结构：

```text
DAG / 多父级有向图
```

用户看到的界面：

```text
QTreeView
```

因此 QTreeView 并不是数据库中的真实树，而是：

> **将图结构按照当前分类路径投影成树状界面。**

例如数据库中：

```text
A → X
B → X
```

UI 中显示：

```text
A
└── X

B
└── X
```

两个 X 使用相同的 `node_id`，但在 Qt Model 中属于两个不同的树节点实例。

---

## 7.2 必须禁止循环引用

允许：

```text
A → B
A → C
B → D
C → D
```

不允许：

```text
A → B
B → C
C → A
```

也不允许：

```text
A → B
A → B
```

后者由：

```sql
UNIQUE(parent_id, child_id)
```

直接避免。

新增关系或移动节点时，必须检查：

> 新增 `parent → child` 后，child 是否能够沿 edges 反向/正向路径再次到达 parent。

若会形成环，则拒绝操作。

---

# 8. 节点语义

节点在数据库中不强制区分四种类型。

可以通过上下文、所在路径和是否包含 PDF 来判断用户语义。

典型情况下：

| 用户概念 | 常见特征 |
|---|---|
| 图书馆 | 顶层节点 |
| 书架 | 图书馆下的分类节点 |
| 库 | 中间组织节点 |
| 容器 | 通常直接持有 PDF 的节点 |

但是：

> 不禁止一个节点同时拥有子节点和 PDF。

因此不需要强制执行：

```text
“容器绝对不能有子节点”
```

这会使系统失去灵活性。

例如用户完全可以创建：

```text
库：马克思
├── 容器：资本论
└── 容器：政治经济学批判
```

也可以：

```text
节点：正在阅读
├── 容器：资本论
└── 库：哲学
```

---

# 9. QTreeView 模型设计

## 9.1 不建议直接用 QStandardItemModel 作为最终模型

早期原型可使用：

```text
QStandardItemModel
```

但最终推荐使用：

```text
QAbstractItemModel
```

原因是：

- 一个数据库节点可以在多个位置显示；
- 需要动态加载子节点；
- 需要支持大量数据；
- 需要区分“显示实例”和“数据库节点 ID”；
- 后期需要拖拽、排序、刷新和懒加载。

建议 Qt Model 中的内部对象包含：

```python
class TreeItem:
    node_id: int
    parent_item: TreeItem | None
    children: list[TreeItem]
    display_path: tuple[int, ...]
```

其中：

- `node_id` 指向数据库真实节点；
- `TreeItem` 本身代表一次显示实例；
- 同一个 `node_id` 可以对应多个 `TreeItem`。

---

# 10. 多父级显示算法

从所有“无父级”的根节点开始构建。

伪代码：

```text
build(parent_item, current_path):
    children = get_children(parent_node_id)

    for child in children:
        if child.id in current_path:
            # 检测到循环引用
            显示循环警告
            跳过该节点
            continue

        创建 TreeItem(child.id)
        加入 parent_item

        build(
            child,
            current_path + {child.id}
        )
```

注意：

不能使用一个全局 `visited` 集合简单地禁止重复节点。

因为：

```text
A → X
B → X
```

X 出现两次本来就是合法情况。

应该维护的是：

> **当前递归路径 `current_path`**

而不是整个模型生命周期内的全局 visited。

这样可以同时满足：

- 允许多父级；
- 防止循环；
- 允许同一个节点在多个路径重复显示。

---

# 11. 主界面设计

建议整体采用：

```text
┌─────────────────────────────────────────────────────────────┐
│ 文件  编辑  查看  工具  设置                                  │
├─────────────────────────────────────────────────────────────┤
│ 🔎 搜索                                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  📚 经济政治                                                │
│   ├─ 📜 马列                                                │
│   │   ├─ 👤 马克思                                  ×2      │
│   │   └─ 👤 恩格斯                                          │
│   └─ 🏛 西欧哲学家                                          │
│       └─ 👤 马克思                                  ×2      │
│                                                             │
│  📚 正在阅读                                                │
│   └─ 🏛 政治                                                │
│       └─ 📄 政治经济学批判                           ×2      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

具体布局可在开发阶段微调。

---

# 12. 节点显示功能

每个节点至少显示：

```text
[图标] [名称]
```

必要时显示：

- 多父级角标；
- PDF 数量；
- 文件缺失警告；
- 自定义状态图标；
- 收藏/重要标记（未来可扩展）。

例如：

```text
📚 马列
👤 马克思       ×2
📄 政治经济学批判
```

其中 `×2` 表示：

> 当前节点至少还有一个其他父级。

这个角标只用于提示，不改变数据结构。

---

# 13. 用户自定义样式

## 13.1 基础样式

节点至少支持：

- 名称；
- 图标；
- 字体加粗；
- 字体颜色。

例如用户可以设置：

```text
经济政治    普通
马列        普通
正在阅读    红色 + 加粗
马克思      蓝色
```

---

## 13.2 图标

支持两类图标：

### 内置图标

例如：

```text
📚
📖
📜
🏛️
👤
🔬
⭐
📌
```

### 自定义图片

支持：

```text
.ico
.png
.svg（视最终 Qt 支持情况）
```

建议用户导入的图标统一复制到：

```text
icons/
```

数据库只保存相对路径：

```text
icons/marx.png
```

避免直接依赖用户原始文件位置。

---

# 14. 节点右键菜单

右键节点时根据上下文显示：

```text
新建子节点
────────────────
添加/关联到其他位置
查看所有位置
────────────────
编辑属性
设置样式
────────────────
打开 PDF
打开全部 PDF
────────────────
从当前父级移除
彻底删除节点
────────────────
重新定位缺失文件
```

不同节点可以根据实际状态隐藏无意义的项目。

---

# 15. 多父级节点操作逻辑

## 15.1 从当前父级移除

例如：

```text
马列
└── 马克思
```

执行：

```text
从当前父级移除
```

只删除：

```text
edge(parent=马列, child=马克思)
```

不会删除：

```text
nodes(id=马克思)
```

因此如果：

```text
西欧哲学家
└── 马克思
```

仍然存在，那么“马克思”继续保留。

---

## 15.2 彻底删除节点

执行：

```text
彻底删除节点
```

则：

1. 删除 node；
2. 删除该 node 参与的所有 edges；
3. 保留实际 PDF 文件，不自动删除磁盘数据。

删除前需要明确提示：

> 该节点当前被 N 个位置引用，彻底删除后所有位置中的该节点都会消失。

---

# 16. “查看所有位置”

右键某节点：

```text
马克思
└── 查看所有位置
```

显示：

```text
马克思当前所在位置：

1. 经济政治 > 马列 > 马克思
2. 经济政治 > 西欧哲学家 > 马克思
```

点击某一项可以：

> 自动展开树并定位到对应显示实例。

这是多父级系统非常重要的可用性功能。

---

# 17. 新建与关联节点

推荐采用两步思想：

## 第一步：正常新建

在：

```text
马克思
```

下选择：

```text
新建子节点
```

默认只创建：

```text
马克思
└── 新节点
```

这样不会增加新用户的认知负担。

## 第二步：需要时再增加位置

创建完成后，可通过：

```text
添加/关联到其他位置
```

选择：

```text
经济政治 > 马列
经济政治 > 西欧哲学家
正在阅读 > 政治
```

从而建立额外 edges。

这种方式兼顾：

- 新手简单；
- 高级用户灵活。

---

# 18. PDF 管理

## 18.1 多 PDF

一个节点可以挂多个 PDF：

```json
[
    "books/capital_1.pdf",
    "books/capital_2.pdf",
    "books/capital_3.pdf"
]
```

因此“容器”本质上不是单文件，而是：

> **一组属于同一逻辑对象的 PDF 文件。**

例如：

```text
容器：资本论

├── 资本论 第一卷.pdf
├── 资本论 第二卷.pdf
└── 资本论 第三卷.pdf
```

---

# 19. 打开 PDF 的交互

## 19.1 双击

若节点：

```text
有子节点
```

双击：

> 展开 / 折叠。

若节点：

```text
无子节点 + 有 PDF
```

双击：

- 只有一个 PDF → 直接打开；
- 多个 PDF → 弹出 PDF 选择框。

若节点：

```text
有子节点 + 同时拥有 PDF
```

推荐将双击行为定义为：

> 展开 / 折叠。

PDF 则从右键菜单或专门的“打开 PDF”入口访问。

这样可以避免双击含义冲突。

---

# 20. PDF 阅读器调用

`services/pdf_launcher.py` 统一处理。

优先级：

```text
用户指定阅读器
        ↓
系统默认 PDF 阅读器
```

跨平台适配：

```python
Windows:
    os.startfile(path)

macOS:
    open path

Linux:
    xdg-open path
```

如果用户指定了可执行文件，则使用：

```python
subprocess.Popen([...])
```

而不是硬编码某一个阅读器。

---

# 21. 文件路径策略

## 21.1 数据库不建议依赖绝对路径

例如不要长期保存：

```text
C:\Users\User\Documents\Books\capital.pdf
```

推荐保存相对路径：

```text
books/capital.pdf
```

---

## 21.2 导出文件采用相对路径

导出图书馆时：

> PDF 路径必须相对于导出文件所在目录计算。

例如：

```text
MyLibrary/
├── library.json
└── books/
    ├── capital.pdf
    └── marx.pdf
```

JSON：

```json
{
    "pdfs": [
        "./books/capital.pdf",
        "./books/marx.pdf"
    ]
}
```

这样用户可以整体复制：

```text
MyLibrary/
```

到另一台电脑。

---

# 22. 缺失文件处理

启动或访问 PDF 时检查：

```text
文件是否存在？
```

若不存在：

```text
⚠ 政治经济学批判
```

并提示：

```text
PDF 文件无法找到：

books/critique.pdf
```

提供：

```text
重新定位文件
```

而不是：

> 删除数据库中的引用。

这样可以防止用户移动文件之后丢失分类信息。

---

# 23. 导入 / 导出

## 23.1 导出目标

“导出图书馆”不是简单导出某个数据库表。

必须保存：

- 节点；
- 节点属性；
- PDF 路径；
- 节点之间的所有关系；
- 顺序；
- 图标；
- 样式；
- metadata；
- 文件格式版本。

---

## 23.2 推荐 JSON 格式

```json
{
    "format": "ap_manager_library",
    "version": "0.1",

    "nodes": [
        {
            "id": "n1",
            "name": "经济政治",
            "pdfs": [],
            "icon": "🏛️",
            "style": {
                "bold": false,
                "color": "#000000"
            },
            "metadata": {}
        },
        {
            "id": "n2",
            "name": "马列",
            "pdfs": [],
            "icon": "📜",
            "style": {
                "bold": false,
                "color": "#000000"
            },
            "metadata": {}
        },
        {
            "id": "n3",
            "name": "马克思",
            "pdfs": [],
            "icon": "👤",
            "style": {
                "bold": true,
                "color": "#B22222"
            },
            "metadata": {}
        },
        {
            "id": "n4",
            "name": "政治经济学批判",
            "pdfs": [
                "./books/critique.pdf"
            ],
            "icon": "📖",
            "style": {
                "bold": false,
                "color": "#000000"
            },
            "metadata": {}
        }
    ],

    "edges": [
        {
            "parent": "n1",
            "child": "n2",
            "sort_order": 0
        },
        {
            "parent": "n2",
            "child": "n3",
            "sort_order": 0
        },
        {
            "parent": "n1",
            "child": "n3",
            "sort_order": 1
        },
        {
            "parent": "n3",
            "child": "n4",
            "sort_order": 0
        }
    ]
}
```

重点：

> 不使用嵌套 `children` 保存最终关系。

因为嵌套结构无法无损表示多父级关系。

---

# 24. 导入策略

导入步骤：

```text
选择 library.json
        ↓
检查 JSON 版本
        ↓
校验节点数据
        ↓
校验 edges
        ↓
检查重复 ID
        ↓
检查循环
        ↓
解析相对路径
        ↓
检查 PDF 是否存在
        ↓
导入数据库
        ↓
刷新 QTreeView
```

缺失 PDF：

> 不阻止整个图书馆导入。

只标记：

```text
⚠ 文件缺失
```

让用户之后重新定位。

---

# 25. 导入时的 ID 规则

导入文件中的：

```text
n1
n2
n3
```

不一定与本机 SQLite 中的：

```text
id=1
id=2
id=3
```

一致。

因此导入时需要维护：

```text
external_id → local_db_id
```

映射。

例如：

```text
n3 → 127
```

然后根据映射重建 edges。

这样可以避免数据库主键冲突。

---

# 26. 数据层核心 API

`database.py` 至少提供：

```python
add_node(name, ...)
get_node(node_id)
update_node(node_id, ...)
delete_node(node_id)

add_edge(parent_id, child_id, sort_order=0)
delete_edge(parent_id, child_id)

get_children(parent_id)
get_parents(child_id)
get_root_nodes()

get_all_positions(node_id)

move_edge(parent_id, child_id, new_sort_order)
```

此外建议提供：

```python
would_create_cycle(parent_id, child_id)
```

用于新增关系前的循环检测。

---

# 27. 图书馆业务层

不要让 UI 直接操作 SQL。

建议：

```text
View
 ↓
Controller
 ↓
Library / Service
 ↓
Database
```

例如：

```text
用户点击“添加到其他位置”
        ↓
app_controller
        ↓
library_service.attach_node(...)
        ↓
cycle check
        ↓
database.add_edge(...)
```

这样未来更换界面或数据库时不会大量修改业务逻辑。

---

# 28. 搜索

建议作为 Phase 4 功能。

搜索范围至少包括：

- 节点名称；
- 作者信息（如果未来增加作者字段）；
- PDF 文件名；
- 标签（未来）。

搜索结果应该能够定位到：

```text
某个 node_id
```

并在 QTreeView 中展开到目标位置。

由于一个节点可能有多个父级，因此搜索结果应该允许：

```text
马克思

出现位置：
1. 经济政治 > 马列 > 马克思
2. 经济政治 > 西欧哲学家 > 马克思
```

---

# 29. 标签系统

不强制写入第一版数据库结构。

可以作为后期扩展：

```json
"metadata": {
    "tags": [
        "哲学",
        "政治经济学",
        "重要"
    ]
}
```

如果未来标签功能发展成熟，再单独拆表。

---

# 30. FDF / PDF 注释扩展

当前版本不负责实现 FDF。

但 `nodes.metadata` 为此预留空间。

未来可以保存：

```json
{
    "annotations": {
        "capital_v1.pdf": "./annotations/capital_v1.fdf"
    }
}
```

或更正式地升级为独立表：

```text
annotations
```

例如：

```sql
CREATE TABLE annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL,
    pdf_path TEXT NOT NULL,
    fdf_path TEXT NOT NULL
);
```

因此：

> 第一版不要把 FDF 逻辑硬编码到核心节点模型中。

应该通过：

```text
services/annotation_handler.py
```

隔离。

---

# 31. 拖拽与排序

## 31.1 同级排序

用户可通过拖拽改变：

```text
sort_order
```

例如：

```text
马克思
恩格斯
列宁
```

拖拽后：

```text
列宁
马克思
恩格斯
```

只需要重新调整同一 `parent_id` 下的 `sort_order`。

---

## 31.2 拖拽建立新关系

允许：

```text
将“马克思”拖到“西欧哲学家”
```

结果是：

```text
add_edge(西欧哲学家, 马克思)
```

而不是把马克思“搬走”。

如果用户希望从原位置彻底移动：

> 可以增加“移动到此处”操作。

两者需要在 UI 中区分：

```text
关联到此处
移动到此处
```

其中：

- **关联** = 新增 edge；
- **移动** = 删除原 edge + 新增新 edge。

---

# 32. 删除语义

必须严格区分三个概念：

### 从当前位置移除

删除一条：

```text
edge
```

### 移动

改变节点的分类关系。

### 彻底删除

删除：

```text
node
```

和相关所有：

```text
edges
```

但：

> 不自动删除 PDF 实体文件。

这是为了避免误删用户的重要书籍文件。

---

# 33. 配置文件

`config.json` 可以包含：

```json
{
    "pdf_reader": {
        "path": ""
    },

    "ui": {
        "window_width": 1200,
        "window_height": 800,
        "window_x": null,
        "window_y": null
    },

    "library": {
        "database_path": "data/library.db"
    }
}
```

未来可增加：

```text
默认展开状态
主题
字体
语言
确认提示偏好
```

---

# 34. 主菜单

建议：

```text
文件
├── 新建节点
├── 导入图书馆
├── 导出图书馆
├── 设置
└── 退出

编辑
├── 撤销（后期）
├── 重做（后期）
└── 删除

查看
├── 展开全部
├── 折叠全部
└── 搜索

工具
├── 文件检查
├── 重新定位缺失 PDF
└── 数据库维护

帮助
├── 使用说明
└── 关于
```

---

# 35. 开发阶段

## Phase 1：数据库与核心模型

目标：

> 先让数据结构正确。

任务：

- [x] 创建 SQLite 数据库；
- [x] 创建 `nodes`；
- [x] 创建 `edges`；
- [x] 创建 `metadata`；
- [x] 实现节点 CRUD；
- [x] 实现 edge CRUD；
- [x] 实现根节点查询；
- [x] 实现子节点查询；
- [x] 实现父节点查询；
- [x] 实现循环检测；
- [x] 编写基础单元测试。

重点：

> **先验证多父级关系，不要先做 UI。**

---

## Phase 2：QTreeView 基础显示

目标：

> 将数据库中的图结构正确投影成树。

任务：

- [x] 实现自定义 `QAbstractItemModel`；
- [x] 根节点加载；
- [x] 子节点递归加载；
- [x] 支持同一 node 在多个父级显示；
- [x] 支持当前路径循环保护；
- [x] 双击展开/折叠；
- [x] 基础刷新机制。

验收条件：

```text
A → X
B → X
```

界面必须显示：

```text
A
└── X

B
└── X
```

同时两个 X 必须拥有相同的数据库 node ID。

---

## Phase 3：节点编辑与视觉自定义

- [x] 新建节点；
- [x] 编辑名称；
- [x] 图标选择；
- [x] 自定义图片；
- [x] 字体加粗；
- [x] 字体颜色；
- [x] 自定义 Delegate；
- [x] 多父级角标；
- [x] 文件缺失警告图标。

---

## Phase 4：PDF 管理

- [x] 添加多个 PDF；
- [x] 移除 PDF；
- [x] PDF 多选；
- [x] 打开 PDF；
- [x] 多 PDF 选择；
- [x] 指定 PDF 阅读器；
- [x] 系统默认阅读器；
- [x] 文件缺失检测；
- [x] 重新定位 PDF。

---

## Phase 5：多父级高级交互

- [x] 查看所有位置；
- [x] 从当前父级移除；
- [x] 彻底删除；
- [x] 关联到其他位置；
- [x] “关联”与“移动”区分；
- [x] 拖拽排序；
- [x] 拖拽建立关联；
- [x] 循环检测提示。

---

## Phase 6：导入与导出

- [x] JSON 导出；
- [x] 相对路径转换；
- [x] JSON 导入；
- [x] 外部 ID 映射；
- [x] edges 重建；
- [x] PDF 存在性检查；
- [x] 图标文件导出/复制策略；
- [x] 版本号；
- [x] 导入失败回滚。

---

## Phase 7：搜索与体验优化

- [x] 节点名称搜索；
- [x] PDF 文件名搜索；
- [x] 搜索结果位置显示；
- [x] 点击搜索结果自动定位；
- [x] 批量重新定位；
- [x] 窗口大小/位置记忆；
- [x] 展开状态记忆；
- [x] 日志系统；
- [x] 操作错误提示优化。

---

## Phase 8：FDF / 注释扩展

- [ ] annotation_handler；
- [ ] FDF 导入；
- [ ] PDF-FDF 关联；
- [ ] 注释入口；
- [ ] 注释文件管理；
- [ ] 根据阅读器能力调用相关参数。

---

# 36. 测试重点

多父级架构是本软件最容易出错的部分，必须重点测试。

## 测试一：普通树

```text
A
└── B
    └── C
```

## 测试二：多父级

```text
A → C
B → C
```

预期 C 显示两次。

## 测试三：多级共享

```text
A → X
B → X
X → Y
```

预期：

```text
A
└── X
    └── Y

B
└── X
    └── Y
```

## 测试四：循环

尝试：

```text
A → B
B → C
C → A
```

必须拒绝。

## 测试五：删除关系

删除：

```text
A → C
```

不能影响：

```text
B → C
```

## 测试六：彻底删除

删除 C 后：

```text
A → C
B → C
```

全部关系都必须消失。

## 测试七：导出 / 导入

要求：

```text
导出 → 清空数据库 → 导入
```

之后：

- 节点数量一致；
- 边数量一致；
- 节点属性一致；
- 多父级结构一致；
- sort_order 一致；
- PDF 相对路径可恢复。

---

# 37. 性能规划

第一版建议直接加载全部节点。

当节点规模增加到数千甚至数万时：

- 使用 `QAbstractItemModel`；
- 子节点按需加载；
- 数据库查询增加索引；
- 避免每次刷新都完整扫描所有节点；
- 搜索使用 SQL；
- 必要时增加缓存。

推荐索引：

```sql
CREATE INDEX idx_edges_parent
ON edges(parent_id);

CREATE INDEX idx_edges_child
ON edges(child_id);

CREATE INDEX idx_edges_parent_sort
ON edges(parent_id, sort_order);
```

---

# 38. 数据库事务

涉及多个操作时应使用事务。

例如“彻底删除节点”：

```text
BEGIN
    删除 edges
    删除 node
COMMIT
```

导入图书馆也应该整体事务化：

```text
BEGIN
    创建 nodes
    创建 edges
    检查关系
COMMIT
```

若任何一步失败：

```text
ROLLBACK
```

避免得到半个图书馆。

---

# 39. 错误处理

软件不能因为单个 PDF 缺失、图标路径失效或某条关系异常而整体崩溃。

错误应分类：

```text
用户操作错误
文件不存在
JSON 格式错误
导入版本不兼容
数据库异常
循环关系
PDF 阅读器启动失败
```

UI 显示用户可理解的信息。

详细技术信息写入日志。

---

# 40. 数据安全原则

本软件的重要原则：

> **分类删除 ≠ 文件删除。**

默认情况下：

```text
删除节点
```

只改变数据库。

不删除：

```text
*.pdf
```

只有未来实现“清理未引用文件”等功能时，才需要单独的、高风险的明确确认流程。

---

# 41. 版本兼容

JSON 导出必须带：

```json
"format": "ap_manager_library",
"version": "0.1"
```

导入器根据版本处理。

未来：

```text
3.0
3.1
4.0
```

可以分别实现：

```python
import_v30()
import_v31()
import_v40()
```

必要时再升级为统一迁移器。

---

# 42. MVP 最小可用版本

第一版不应该一次实现所有高级功能。

建议 MVP 只包含：

```text
SQLite
+
节点 CRUD
+
多父级 edges
+
QTreeView
+
节点图标/加粗/颜色
+
多 PDF
+
第三方阅读器打开
+
缺失文件提示
+
JSON 导入/导出
+
相对路径
```

先确保：

> **“我可以稳定地把整个本地图书体系组织起来，并且同一个东西可以出现在多个分类中。”**

搜索、拖拽、FDF、标签、撤销/重做等功能放到 MVP 之后。

---

# 43. 最终架构原则

整个软件最终遵循以下结构：

```text
                    ┌──────────────┐
                    │    PySide6   │
                    │   QTreeView  │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ AppController│
                    └──────┬───────┘
                           │
              ┌────────────┼─────────────┐
              ▼            ▼             ▼
       ┌────────────┐ ┌──────────┐ ┌──────────────┐
       │Library      │ │ PDF      │ │ Import /     │
       │Service      │ │ Launcher │ │ Export       │
       └──────┬──────┘ └──────────┘ └──────────────┘
              │
              ▼
       ┌──────────────────┐
       │     SQLite       │
       │                  │
       │ nodes + edges    │
       └──────────────────┘
```

核心数据关系：

```text
Node
  │
  ├── 自身属性
  │
  ├── PDF
  │
  └── Metadata

Edge
  │
  ├── Parent
  └── Child
```

最终模型：

```text
                     多父级 DAG
                         │
                         ▼
                  QAbstractItemModel
                         │
                         ▼
                      QTreeView
```

---

# 44. 最终产品定位

本软件最终不是：

```text
“一个只能把 PDF 分文件夹放进去的程序”
```

而是：

```text
“一个允许用户按照自己的思想组织 PDF，
同一个知识对象可以同时属于多个分类，
并且可以通过便携的图书馆文件进行迁移的本地书籍知识管理器。”
```

最重要的设计决定可以概括为四点：

**一、用户看到的是四级语义，但数据库不强制四级。**

**二、用户操作的是树，但底层保存的是多父级图。**

**三、节点是独立实体，分类位置由 edges 决定。**

**四、分类信息与 PDF 实体文件分离，导入导出使用相对路径保证可迁移。**

这四点应作为后续所有功能开发时的最高优先级设计约束。
