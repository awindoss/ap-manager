# Phase 3 推进可行性评估

> 评估对象：ap_manager 当前代码库（HEAD `f2aa38b` Phase 1 + 未提交的 Phase 2 实现）
> 评估日期：2026-10-25
> 依据文档：`_mds/plan.md` 第 13/35 节、`_mds/stage.md` Phase 3

---

## 一、结论

**可行，风险低，不需要数据库迁移，也不需要改动图结构逻辑。**

Phase 3 的 7 项任务全部落在「表现层 + 3 个对话框 + 1 个控制器接口」上，
而它们依赖的数据层能力已经具备：

- `nodes` 表已有 `icon`、`style_bold`、`style_color` 三列（plan.md 6.1）；
- `Database.update_node()` 的白名单已包含这三个字段（database.py:194-201）；
- `LibraryService.create_node(name, parent_id, **kwargs)` 已支持带样式建节点；
- `TreeModel.data()` 已为 `DecorationRole` / `FontRole` / `ForegroundRole` 预留占位
  （tree_model.py:336-344），且 `NodeIdRole` / `DisplayPathRole` 已可用。

真正的工作量集中在：`utils/icon_utils.py`、`views/delegates/tree_delegate.py`、
3 个对话框、控制器写入接口、右键菜单，以及 **两处必须先处理的体验/性能问题**（见第四节）。

工期估计：**3 ~ 3.5 人日**（stage.md 给的是 2 天；多出的部分主要是「刷新保持展开状态」和测试）。

---

## 二、当前基线核验（实测）

| 项目 | 结果 |
|---|---|
| 单元测试 | **29 项全部通过**（Python 3.11.15 / PySide6 6.11.1 / pytest 9.1.1，offscreen 平台） |
| 测试分布 | `test_database.py` 12 项、`test_tree_model.py` 10 项、`test_main_window.py` 7 项 |
| Phase 2 手工验收 | `logs/phase2_tree_preview.png`：多父级节点「政治经济学批判」按 3 条路径重复显示，状态栏「节点 8 / 显示实例 11 / 根节点 2」 |
| 数据层 | 建表、索引、级联删除、循环检测（BFS）、全路径回溯（DFS）均已实现并有测试 |
| 示例数据 | `data/library.db` 当前是**空库**（nodes=0, edges=0）；截图数据来自临时库 |
| 版本库 | HEAD 只有 Phase 1；Phase 2 的 7 个新文件 + 4 个修改**尚未提交** |

模型层实测（off-screen 探针）：

```
expanded before refresh: True  True
expanded after  refresh: False False      ← 刷新丢失展开状态
selection after refresh: valid=False       ← 刷新丢失选中
DecorationRole=None  FontRole=None  ForegroundRole=None   ← Phase 3 占位符合预期
emoji 绘制管线可运行（headless 下字体列表为空，字形需在真实 GUI 复核）
SVG 图标可加载（QImageReader 支持 svg/svgz，QIcon 非空）
```

---

## 三、逐项对照

| stage.md 任务 | 现有支撑 | 缺口 | 工作量 | 风险 |
|---|---|---|---|---|
| 3.1 `utils/icon_utils.py` | `DEFAULT_ICON_EMOJIS`、`VALID_ICON_EXTENSIONS`、`ICONS_PATH` 已定义 | 全新文件 | 0.5 d | 低 |
| 3.2 `views/delegates/tree_delegate.py` | `QTreeView` 已就绪 | 全新文件（角标绘制） | 0.5~1 d | **中** |
| 3.3 `tree_model.py` 返回 Font/Foreground/Decoration | 三个 role 已有占位分支 | 补实现 + 父级计数缓存 | 0.5 d | 低 |
| 3.4 `add_node_dialog.py` | `create_node` 支持 `parent_id` + 样式参数 | 全新文件 + controller 接口 | 0.5 d | 低 |
| 3.5 `node_properties_dialog.py` | `update_node` 白名单已覆盖全部字段 | 全新文件 | 0.5 d | 低 |
| 3.6 `icon_selector_dialog.py` | `ICONS_PATH`、扩展名常量 | 全新文件（复制文件 + 相对路径） | 0.5 d | 低~中 |
| 3.7 右键菜单 | `MainWindow` 已有菜单栏骨架 | `customContextMenuRequested` 连接 | 0.25 d | 低 |

验收对照：

| 验收标准 | 依赖 | 可行性 |
|---|---|---|
| 新建节点可指定图标/加粗/颜色 | 3.4 + controller.create_node + refresh | ✅ |
| 编辑后树视图立即更新 | 3.5 + refresh（需修展开状态） | ⚠️ 见 P0-1 |
| 多父级节点显示角标 ×2 | 父级计数 + 3.2 | ⚠️ 见 P0-2 |
| 自定义图片图标正常显示 | 3.6 + 3.1 + 3.2 | ✅ |

---

## 四、必须先处理的问题

### P0-1 刷新会折叠整棵树（实测确认）

`TreeModel.refresh()` 用 `beginResetModel/endResetModel` 全量重建，Qt 会丢弃
展开状态与选中项。Phase 3 的每次「新建 / 编辑」都会走这条路径，结果是：
**改一个名字，整棵树收起来，用户还要重新展开到原位置。**
验收字面上能过，体验上不可接受，且 Phase 5/7 还会重复踩。

建议在 `MainWindow` 里做最小修复（约 20 行）：

```python
def refresh(self) -> None:
    expanded = self._collect_expanded_paths()   # DFS，取 DisplayPathRole 集合
    self.model.refresh()
    self._restore_expanded(expanded)            # 按 display_path 精确匹配
    self._update_status()
```

单节点属性修改还可以更轻：给 `TreeModel` 加 `notify_node_changed(node_id)`，
遍历 `find_items_by_node_id()` 命中的实例、替换 `item.node` 后对每处
`emit dataChanged(index, index, [FontRole, ForegroundRole, DecorationRole])`。
这样连 reset 都不需要，展开状态天然保留。建议**两套都做**：
改属性用 `dataChanged`，新建节点用「保留展开状态的 refresh」。

### P0-2 角标需要父级计数，但当前没有聚合查询

角标语义是 `len(get_parents(node_id)) > 1`，而 `get_node_parents()` 每次调用
都要开连接并逐级查节点。若在 delegate / `data()` 里逐行调用，就是 O(N) 次连接：

```
实测：310 个节点逐行查询父级 = 0.156 s（本机，连接开销被沙箱放大）
```

正确做法是单条聚合 SQL，每次构建缓存一次：

```python
# models/database.py
def get_parent_counts(self) -> dict[int, int]:
    with self.connection() as conn:
        rows = conn.execute(
            f"SELECT {constants.COLUMN_EDGE_CHILD_ID}, COUNT(*) "
            f"FROM {constants.TABLE_EDGES} GROUP BY {constants.COLUMN_EDGE_CHILD_ID}"
        ).fetchall()
    return {row[0]: row[1] for row in rows}
```

`TreeModel.load_roots()` 时缓存为 `self._parent_counts`，`data()`/delegate 只读内存。
注意：Phase 5 的「关联到其他位置」会改变计数，届时在 refresh 时重建即可。

### P0-3 控制器缺少写入入口

`AppController` 目前只有只读透传和一个 Phase 4 桩 `request_open_pdfs`。
按 plan.md 第 27 节的分层（View → Controller → Library → Database），
Phase 3 应补：`create_node(name, parent_id, **style)`、`update_node(node_id, **changes)`、
`get_node_parents(node_id)`。增量小，但别让对话框直接拿 `library` 操作（虽然
`MainWindow` 现在就是这么持有 `controller.library` 的）。

---

## 五、实现建议（降低风险的关键点）

1. **把 3.3 和 3.2 拆成两步交付**
   先只补 model roles：`DecorationRole` 返回 `QIcon`、`FontRole` 返回粗体 `QFont`、
   `ForegroundRole` 返回 `QColor`。这三个 role 一旦生效，默认 delegate 就能显示
   图标/粗体/颜色，**不写 delegate 也能完成一半验收**。
   然后用 `QStyledItemDelegate.paint()` 只叠加角标（先 `super().paint()` 再在
   右侧留白区画小字号 `×N`），把「绘制回归」的风险隔离在一个小改动里。

2. **`Node.icon` / `style_color` 可能为 NULL**
   schema 允许 NULL，`_row_to_node()` 原样透传 → `Node.icon` 实际可能是 `None`。
   在 `_row_to_node()` 里归一化为 `""` / `#000000`，否则 `QIcon(None)`、
   `QColor(None)` 会在 delegate 里埋雷。

3. **图标缓存与回退**
   `load_icon()` 必须按 `(icon_str, size)` 缓存（`data()` 每帧都会被调用）；
   自定义图片要走 `QPixmap.isNull()` 检查，损坏/丢失时回退到 emoji 或空图标并
   `log_warning`，不能抛异常。相对路径要校验在 `ICONS_PATH` 之内，防止
   `../../` 越界。

4. **自定义图标入库规则**
   复制到 `icons/` 后用去重文件名（如 `<stem>_<hash8>.<ext>`），DB 只存
   `icons/xxx.png`。`VALID_ICON_EXTENSIONS` 已限定 png/ico/svg；SVG 在本机
   PySide6 6.11.1 下已验证可加载。文件名含中文无需特殊处理（SQLite TEXT / UTF-8）。

5. **颜色校验**
   `QColor("#B22222").isValid()` 为真才写库，否则回退 `DEFAULT_TEXT_COLOR`；
   建议统一存 `#RRGGBB`（`QColor.name()`），避免 `#fff` 与 `#FFFFFF` 混用。

6. **行高**
   `QTreeView.setUniformRowHeights(True)` 与自定义 `sizeHint` 会打架。
   图标固定 16px、角标用 `QFont` 缩小行高不变，可以保持 `True`；
   若允许用户放大图标，需改 `False` 并自行处理性能。

7. **对话框返回后的定位**
   新建后刷新并选中新节点（`find_items_by_node_id` + `tree_view.scrollTo`），
   否则用户找不到刚建的东西。

---

## 六、范围歧义需要先拍板

`plan.md` 第 35 节把「文件缺失警告图标」列在 Phase 3，而 `stage.md` 把它放在
Phase 4.7（依赖 `services/path_manager.py`），两处文档冲突。

建议：**Phase 3 不做**，理由：
- 需要 PDF 路径解析（Phase 4 的 `path_manager`），提前做会引入重复实现；
- `os.path.exists()` 逐行调用同样需要缓存，属于 Phase 4 的性能设计；
- Phase 3 的验收标准里也没有它。

如果坚持要做，最小实现是：`TreeModel` 每次构建时批量检查一次并缓存
缺失集合，delegate 在图标左上角叠一个 `⚠️`，不引入 `path_manager`。

---

## 七、实施顺序（建议）

1. **先提交 Phase 2**（7 新 + 4 改），建立可回滚基线；
2. `Database.get_parent_counts()` + `TreeModel` 角色/缓存 + 单测；
3. `utils/icon_utils.py` + 单测（emoji / png / svg / 缺失 / 路径越界）；
4. `AppController` 写入接口 + 3 个对话框 + 对话框单测（monkeypatch `exec`）；
5. 右键菜单 + 刷新保持展开状态；
6. `tree_delegate` 角标 + 渲染冒烟测试 + **真实 GUI 手测**（headless 下无法验证
   emoji 字形与主题配色）。

---

## 八、风险清单

| 风险 | 影响 | 缓解 |
|---|---|---|
| delegate 绘制回归（选中高亮、省略号、交替行色） | 视觉瑕疵 | 先 roles 后 delegate；`super().paint()` 打底 |
| emoji 字体缺失/字形不显示 | 图标空白 | 字体回退 + 空图标兜底；真实 GUI 复核 |
| 自定义图标文件损坏/被删 | 抛异常或空白 | `QPixmap.isNull()` + 日志 + 回退 |
| 全量刷新在大量节点下变慢 | 编辑卡顿 | 目前 310 项 0.17 s；万级再上增量/懒加载 |
| 展开状态恢复用 display_path | 多父级下需按路径精确匹配 | 用 `DisplayPathRole` 元组做键，不要用 node_id |

---

## 九、环境与验证方式

- **解释器**：`D:\Anaconda\envs\pyside\python.exe`（3.11.15 + PySide6 6.11.1 + pytest 9.1.1）。
  PATH 上默认的 `python` 是 `pytorch` 环境，**没有 pytest**，直接 `python -m pytest` 会失败。
- **测试命令**：`QT_QPA_PLATFORM=offscreen python -m pytest`（第 1 步提交后建议写进 README）。
- **沙箱限制（与项目无关）**：pytest 的 `tmp_path` 用 `mode=0o700` 建目录，在本沙箱下
  不可列举，整批用例会在 fixture 阶段报 `PermissionError`；本次评估用临时 harness
  绕过后 29 项全绿。正常机器上不存在该问题。
- **磁盘写入观察**：本工作区单次 SQLite commit 实测约 0.59 s（50 次独立事务 29.3 s），
  而一次建节点会写 2~4 个事务。若真实机器也这样，新建节点会有明显卡顿；
  建议在 SSD 上复核，或把 `create_node` 的两个写操作（node + edge）合并为一个事务。
- **文档冗余**：`views/plan.md` 与 `_mds/plan.md` 内容完全相同，`views/stage.md` 是
  重排版本；建议留一份，避免后续按错文档施工。

---

## 十、Phase 3 验收测试清单（建议新增 ≥ 12 项）

- [ ] 新建子节点：名称 / 图标 / 加粗 / 颜色 正确入库并显示；
- [ ] 编辑名称后树中立即更新，且**展开状态与选中项保持**；
- [ ] 多父级节点在两条路径上都显示 `×2`，单父级不显示；
- [ ] 自定义 png / svg / ico 图标正常显示；
- [ ] 图标文件被删除后回退不崩溃、有日志；
- [ ] 非法颜色值回退为 `#000000`；
- [ ] `Node.icon` 为 NULL 时正常渲染；
- [ ] 空名称/超长名称的输入校验；
- [ ] 图标选择器复制文件后 DB 存相对路径、文件在 `icons/` 下；
- [ ] 右键菜单在根节点 / 子节点 / 空白处的行为正确；
- [ ] 回归：原有 29 项测试全绿。

---

## 十一、总体判断

Phase 1/2 的完成度高于 stage.md 的要求（有连接复用、循环兜底、不可达节点告警、
截断保护、29 项测试），为 Phase 3 提供了干净的地基。Phase 3 没有架构级风险，
主要成本在细节打磨。**建议按第七节的顺序推进，先提交 Phase 2，并把
「刷新保持展开」「父级计数聚合查询」作为 Phase 3 的第一批改动。**
