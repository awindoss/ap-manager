# Phase 3 完成报告：节点编辑与视觉自定义

> 完成日期：2026-10-25
> 代码基线：Phase 1 + Phase 2 工作树
> 验证环境：Python 3.11.15 / PySide6 6.11.1 / pytest 9.1.1
> 验证结果：**117 项测试全部通过**

---

## 一、结论

`_mds/plan.md` 第 35 节 Phase 3 的 9 项检查全部完成，`_mds/stage.md` Phase 3 的
3.1 ~ 3.7 全部落地；`_mds/phase3_feasibility.md` 第四节列出的三个 P0 问题
（刷新折叠整棵树、角标缺少父级计数聚合、控制器缺少写入入口）已修复。

未改动数据库结构，未改动图结构（nodes + edges）语义，`data/library.db` 保持为空库。

---

## 二、交付对照

| stage.md 任务 | 实现 | 验证 |
|---|---|---|
| 3.1 `utils/icon_utils.py` | emoji 渲染、png/ico/svg 加载、`(icon, size)` 缓存、图标目录越界校验、自定义图片导入（内容哈希去重） | `tests/test_icon_utils.py`（19 项） |
| 3.2 `views/delegates/tree_delegate.py` | 在默认绘制之上叠加右对齐 `×N` 角标；为角标预留宽度，避免长名称与角标重叠 | `tests/test_tree_delegate.py`（3 项）+ 真实渲染复核 |
| 3.3 `views/tree_model.py` 增强 | `DecorationRole` / `FontRole` / `ForegroundRole` / `ParentCountRole`；`notify_node_changed()` 原地刷新；`find_index_by_display_path()` | `tests/test_tree_model.py`（20 项） |
| 3.4 `add_node_dialog.py` | 名称、父级提示、图标、加粗、颜色；空名称与超长名称校验 | `tests/test_dialogs.py`（21 项） |
| 3.5 `node_properties_dialog.py` | 编辑名称与样式；PDF 列表只读展示（管理留待 Phase 4）；只返回实际变化的字段 | 同上 |
| 3.6 `icon_selector_dialog.py` | 内置 emoji 网格、自定义图片导入、清除图标、预览 | 同上 + 对话框截图复核 |
| 3.7 右键菜单 | `customContextMenuRequested`；节点菜单含新建子节点/编辑属性/设置样式/展开/折叠；空白处只提供新建根节点与刷新 | `tests/test_main_window.py`（19 项） |
| plan.md §35 文件缺失警告图标 | 批量扫描 PDF 存在性，在节点图标右下角叠加红色 `!` 警告点，tooltip 列出缺失路径 | `tests/test_tree_model.py` / `tests/test_path_manager.py` |

**额外交付**：

- 菜单栏加入“新建根节点 / 新建子节点 / 编辑属性 / 设置样式”，带 `Ctrl+N`、
  `Ctrl+Shift+N`、`F2` 快捷键；无选中项时相关菜单自动禁用。
- 新建节点后自动展开路径、选中并滚动到新节点。
- 状态栏增加“缺失 PDF N”。

---

## 三、P0 修复

### P0-1 刷新丢失展开状态与选中项

`MainWindow.refresh()` 在 `model.refresh()` 前收集所有展开实例的
`DisplayPathRole` 与当前选中路径，重建后按路径精确恢复（不使用 `node_id`，
因为多父级节点有多个实例）。

编辑属性走更轻的路径：`TreeModel.notify_node_changed()` 替换实例的 `node`
并对每处实例发 `dataChanged`，不触发 `modelReset`，展开状态与选中项天然保留。
验证：`test_refresh_preserves_expansion_and_selection`、
`test_edit_node_updates_in_place_and_keeps_selection`。

### P0-2 角标父级计数

新增 `Database.get_parent_counts()`（单条 `GROUP BY` 聚合）与
`LibraryService.get_parent_count_map()`；`TreeModel.load_roots()` 每次构建缓存
`_parent_counts`，`data()` 与 delegate 只读内存，不再逐行开数据库连接。

### P0-3 控制器写入入口

`AppController` 新增：

```python
create_node(name, parent_id=None, icon="", style_bold=False, style_color=...)
update_node(node_id, *, name=None, icon=None, style_bold=None, style_color=None)
get_node_parents(node_id)
get_parent_count_map()
```

名称校验（去空白、非空、≤200 字符）与样式归一化都在控制器完成，对话框只负责
收集值，保持 `View → Controller → Library → Database` 的调用方向（plan.md §27）。

---

## 四、文件清单

### 新增

```text
utils/icon_utils.py
services/path_manager.py
views/delegates/__init__.py
views/delegates/tree_delegate.py
views/dialogs/__init__.py
views/dialogs/node_style_editor.py      # 新建/属性对话框共用的样式编辑器
views/dialogs/add_node_dialog.py
views/dialogs/node_properties_dialog.py
views/dialogs/icon_selector_dialog.py

tests/test_icon_utils.py
tests/test_path_manager.py
tests/test_node_style.py
tests/test_tree_delegate.py
tests/test_dialogs.py
tests/test_controller_editing.py
```

### 修改

```text
models/node.py              # __post_init__ 归一化；颜色/图标工具函数
models/database.py          # get_parent_counts()；update_node 规范化样式
models/library.py           # get_parent_count_map()
controllers/app_controller.py
views/tree_model.py         # 视觉角色、父级计数、原地通知、显示路径定位、缺失 PDF
views/main_window.py        # 委托、菜单、右键菜单、刷新状态恢复、新建/编辑流程
utils/constants.py          # TREE_ICON_SIZE、MAX_NODE_NAME_LENGTH
_mds/plan.md                # Phase 1~3 检查项勾选
```

### 测试扩展

| 文件 | 项数 |
|---|---:|
| `tests/test_database.py` | 13 |
| `tests/test_tree_model.py` | 20 |
| `tests/test_main_window.py` | 19 |
| `tests/test_dialogs.py` | 21 |
| `tests/test_icon_utils.py` | 19 |
| `tests/test_controller_editing.py` | 11 |
| `tests/test_path_manager.py` | 6 |
| `tests/test_node_style.py` | 5 |
| `tests/test_tree_delegate.py` | 3 |
| **合计** | **117** |

---

## 五、关键设计决定

1. **角标位置**：与 plan.md §11 的示意图一致，`×N` 右对齐在行尾，而不是紧贴名称，
   以免多父级节点名称较长时与角标挤在一起。
2. **默认颜色不覆盖主题**：`style_color == "#000000"` 时 `ForegroundRole` 返回
   `None`，让平台调色板决定默认文字色（深色主题下仍是可读的浅色）；只有用户
   显式选择其他颜色时才返回 `QColor`。
3. **编辑用 `dataChanged`，新建用“保留状态的 refresh”**：既保证一致性，又避免
   改一个名字就收起整棵树。
4. **自定义图标入库规则**：复制到 `icons/`，文件名 `stem_<sha256[:8]>.<ext>`，
   数据库只存 `icons/xxx.png`；同一文件重复导入不会产生副本；解析时强制校验
   路径位于 `icons/` 内，拒绝 `../` 越界。
5. **图标失败不抛异常**：缺失、损坏、不支持的扩展名都返回空 `QIcon` + 日志，
   树视图只是不画图标，不影响节点操作。
6. **缺失 PDF 只提示、不删数据**：扫描到缺失文件后不修改 `nodes.pdf_paths`，
   仅在图标上叠加红色 `!` 并在 tooltip 中列出路径（plan.md §22）。
   `services/path_manager.py` 是 Phase 4 的正式落点，本阶段只实现存在性检查，
   Phase 4 可在此基础上增加“重新定位/books 根目录”等能力，不会重复实现。
7. **文档冲突的处理**：plan.md §35 把“文件缺失警告图标”列在 Phase 3，stage.md
   4.7 列在 Phase 4。本阶段按 plan.md 先交付最小版本，避免 Phase 3 留下未勾选项；
   PDF 管理与重新定位仍留给 Phase 4。

---

## 六、验证方式

```powershell
# 在项目根目录
python -m pytest
```

本次实际执行结果：

```text
117 passed in 59.34s
```

真实 GUI（非 offscreen）渲染复核通过，截图见
`logs/phase3_preview.png`（该目录被 `.gitignore` 忽略，属于本地验证产物）。
覆盖场景：多父级节点两个实例均显示 `×2`、自定义图片图标、emoji 图标、加粗、
自定义颜色、选中行角标反色、缺失 PDF 警告点、状态栏计数。

> 环境备注：当前 DSH Windows 文件沙箱中，pytest 用 `mode=0o700` 创建的
> `tmp_path` 目录无法被列举。本次验证使用一个仅存在于本地的启动器放宽该目录
> 模式后运行，启动器未纳入版本库；普通开发机直接使用上面的命令即可。

> 版本库备注：后续已补提交 —— `0078c49`（Phase 3 complete）与 `5a1736d`（Phase 3 additional fixes）。

---

## 七、后续阶段衔接

- **Phase 4**：扩展 `services/path_manager.py` 与 `pdf_launcher.py`；在右键菜单加入
  “管理 PDF / 打开 PDF / 重新定位”；`NodePropertiesDialog` 的 PDF 只读区可替换为
  可编辑的 `PdfManagementDialog`。
- **Phase 5**：`attach_nodes` / `detach_nodes` 后调用 `model.refresh()` 即可重建
  `_parent_counts`；`find_index_by_display_path()` 可直接用于“查看所有位置”的定位。
- **Phase 6**：导出时 `icon_utils.import_custom_icon` 的哈希命名规则便于把
  `icons/` 一并复制到导出目录；`path_manager` 可提供相对路径转换。
- **Phase 7**：展开状态收集/恢复逻辑已在 `MainWindow` 中，可抽取到
  `settings_manager.py` 持久化到 `config.json`。

---

*本报告依据 `_mds/plan.md`、`_mds/stage.md` 与 `_mds/phase3_feasibility.md` 编写。*
