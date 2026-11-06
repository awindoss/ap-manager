# Phase 5 完成报告：多父级高级交互

> 完成日期：2026-11-01
> 代码基线：Phase 1 + 2 + 3 + 4 工作树
> 验证环境：Python 3.11.15 / PySide6 6.11.1 / pytest 9.1.1（Windows）
> 验证结果：**299 项测试全部通过**（Phase 4 基线 228 项 + 本阶段新增 71 项）

---

## 一、结论

`_mds/plan.md` 第 35 节 Phase 5 的 8 项检查全部完成，`_mds/stage.md` Phase 5
的 5.1 ~ 5.5 全部落地：

| stage.md 任务 | 实现 | 验证 |
|---|---|---|
| 5.1 `choose_parent_dialog.py` | 可勾选父级树；自身、后代、已关联位置不可选；支持“关联”（多选）与“移动”（单选）两种模式；重复显示路径按 `node_id` 同步勾选 | `tests/test_relation_dialogs.py`（11 项） |
| 5.2 `node_positions_dialog.py` | 列出全部“根 → 节点”路径，标记当前位置；单击/双击/“定位”均返回精确 `DisplayPath` | 同上 + 主窗口定位测试 |
| 5.3 右键菜单 | “关联到其他位置… / 移动到其他位置… / 查看所有位置… / 从当前父级移除 / 彻底删除节点…”；编辑菜单同步入口与快捷键 | `tests/test_main_window_phase5.py`（22 项） |
| 5.4 拖拽支持 | `LibraryTreeView` 自定义 MIME 与拖放；拖到节点上询问“关联/移动”，拖到同级兄弟之间调整 `sort_order`；支持多选关联 | `tests/test_library_tree_view.py`（13 项） |
| 5.5 循环检测及时反馈 | 选择对话框预先禁用；拖拽悬停阶段拒绝并显示原因；控制器写入前再次检查并抛 `GraphCycleError` | `tests/test_controller_relations.py`、`tests/test_library_relations.py` |

额外交付：

- “移动”不再只存在于拖拽：编辑菜单/右键菜单均可打开移动目标选择框。
- 状态栏在拖拽被拒绝时立即显示原因（自身、循环、跨父级排序等）。
- 图变更后自动重建父级计数与 `×N` 角标；新增位置自动展开并选中。
- 修复了一个 Phase 1 遗留的排序缺陷：`add_node_with_parent()` 过去把
  `sort_order` 固定写成 `0`，多个子节点只能靠 `edge id` 兜底排序；
  现在按 `MAX(sort_order) + 1` 追加，删除兄弟后再新增也不会撞号。

---

## 二、关键设计决定

1. **以“显示实例”为操作单位**
   “从当前父级移除”“移动到其他位置”“查看所有位置定位”都使用
   `DisplayPath`（根到该行的 `node_id` 元组），而不是只传 `node_id`。
   同一个 `node_id` 可以出现多次，只有路径能确定用户实际指的是哪一条边
   （plan.md §7.1、§15.1）。

2. **关联与移动的语义边界**
   - 关联：新增一条 `edge`，原位置保留；
   - 移动：删除当前实例的旧 `edge`，再新增到目标父级；
   - 目标位置已包含该节点时，移动退化为“合并位置”——只删除旧边，
     不触发 `UNIQUE(parent_id, child_id)`；
   - 根节点没有旧边，因此根实例的“移动”等价于一次关联，并在结果类型中
     明确标记为 `attached`。

3. **批量关联允许部分成功**
   拖拽多选、或一次选择多个父级时，`AppController` 返回
   `AttachResult(attached / already / errors)` 而不是在第一个失败处中断。
   重复位置、缺失节点、循环、数据库错误分别归类；UI 只对错误弹一次汇总提示，
   已经成功的关系不回滚。

4. **循环检测三层防线**
   - 选择父级对话框：预先禁用自身与全部后代；
   - 拖拽悬停：`would_create_cycle()` 预检查，拖放指示器直接拒绝并说明原因；
   - 控制器/业务层：写入前最终检查，抛 `GraphCycleError`（`ValueError` 子类）。
   这样即使绕过 UI 直接调用控制器，图也保持无环。

5. **排序只改 `sort_order`，不增删边**
   `Database.update_edge_sort_orders()` 在同一个事务里先校验“当前子节点集合
   与请求集合完全一致”，再统一重编号为 `0..n-1`；中途任何一条边消失都会
   整体回滚。拖拽排序被限制在同一个父级的同一显示实例下，避免用户误以为
   跨父级拖拽会移动节点。

6. **删除的不可逆性明确告知**
   “彻底删除”确认框列出被引用的位置数（最多展示 5 条路径）、子节点数量、
   “磁盘 PDF 不会被删除”以及“此操作不可撤销”，默认按钮为“否”（plan.md §15.2、§40）。
   “从当前父级移除”则只删一条边；节点若无其他位置会变成根节点，仍可见。

7. **刷新策略**
   图的增删（关联、移除、移动、排序、彻底删除）都会改变父级计数与可达路径，
   因此走 `MainWindow.refresh()`：重建投影、更新角标、并恢复展开路径与选中项。
   只有“修改名称/图标/样式/PDF”仍使用 `notify_node_changed()` 的无重置路径。

8. **拖拽落点规则**
   - 落在节点上：询问“关联到此位置 / 移动到此位置”（多选时只能关联）；
   - 落在同级兄弟的上/下 30%：排序；
   - 落在空白处：拒绝（不隐式创建根位置）；
   - 顶层节点排序：拒绝（根节点没有 `sort_order`，当前按数据库 ID 稳定显示）。

9. **对话框本身不写库**
   `ChooseParentDialog` / `NodePositionsDialog` 只收集用户选择；取消不会产生任何
   修改。所有写入仍遵循 View → Controller → Library → Database（plan.md §27）。

---

## 三、文件清单

### 新增

```text
views/library_tree_view.py              # 自定义拖放视图、MIME、落点判定、指示器
views/dialogs/choose_parent_dialog.py   # 选择目标父级（关联/移动）
views/dialogs/node_positions_dialog.py  # 查看所有位置并定位

tests/test_library_relations.py
tests/test_controller_relations.py
tests/test_relation_dialogs.py
tests/test_library_tree_view.py
tests/test_main_window_phase5.py
```

### 修改

```text
models/database.py          # get_edge / max+1 排序 / 事务重排 / descendants
models/library.py           # GraphCycleError、attach/detach/move、reorder、descendants
controllers/app_controller.py  # NodePosition / AttachResult / MoveOutcome 及关系 API
views/tree_model.py         # ItemIsDragEnabled、display_path_for_index
views/main_window.py        # 关系菜单、位置/关联/移动/移除/删除、拖放处理、精确展开
utils/constants.py          # 拖拽 MIME、指示器样式常量
_mds/plan.md                # Phase 5 八项勾选
```

### 测试分布

| 文件 | 项数 | 说明 |
|---|---:|---|
| `tests/test_library_relations.py` | 13 | 边增删、循环、后代、排序、路径 |
| `tests/test_controller_relations.py` | 12 | 批量关联结果、移动五种结果、位置名称解析 |
| `tests/test_relation_dialogs.py` | 11 | 父级选择规则、重复路径同步、单选移动、位置列表与单击定位 |
| `tests/test_library_tree_view.py` | 13 | MIME 往返、关联/排序/拒绝落点、真实 drop 信号 |
| `tests/test_main_window_phase5.py` | 22 | 菜单状态、移除/删除确认、关联/移动流程、拖放与定位 |
| **新增合计** | **71** | |
| 既有测试 | 228 | 全部通过，无回归 |

---

## 四、验证方式

```powershell
# 项目根目录
D:\Anaconda\envs\pyside\python.exe -m pytest
```

本次实际执行结果：

```text
299 passed in 308.12s (0:05:08)
```

GUI 冒烟复核使用真实 Windows 平台渲染，截图保存在 `logs/`（该目录被
`.gitignore` 忽略，属于本地验证产物）：

- `logs/phase5_main_window.png`：多父级 `马克思`、`资本论`、`政治经济学批判`
  在两条路径下同时显示，右侧 `×2` 角标与状态栏计数正确。
- `logs/phase5_choose_parent.png`：自身及后代标为“不可选”，已关联的父级标为
  “已关联”，其余位置可勾选。
- `logs/phase5_positions.png`：`马克思` 的两个完整路径，当前位置高亮。
- `logs/phase5_context_menu.png`：新增的关系菜单项与原有 PDF 菜单项的排版。

> 环境备注：当前 DSH Windows 文件沙箱中，pytest 的 `tmp_path`（`mode=0o700`）
> 目录不可读写；本次沿用本地启动器把临时目录模式放宽到 `0o755` 后运行。
> 启动器位于 `logs/`，未纳入版本库；普通开发机直接使用上面的命令即可。

> 版本库备注：已提交为 `8b5e2b8`（Phase 5 complete）。

---

## 五、已知边界

- 顶层节点的顺序仍由数据库 ID 决定，不支持拖拽排序；`sort_order` 属于
  `edges`，根节点没有入边（plan.md §31.1 讨论的是“同级排序”，顶层可后续用
  `nodes` 上的独立顺序字段扩展）。
- 多选拖拽只支持“关联”，不支持一次移动多个位置；移动一次只处理一个显示实例，
  避免同一个 `node_id` 的多个实例被移动到同一父级后产生歧义。
- 拖拽接近视图边缘时没有实现自动滚动，节点很多时需要先滚动到可见范围。
- 拖到空白区域不会隐式创建顶层位置；这是有意的保守策略。

---

## 六、后续阶段衔接

- **Phase 6**：`get_all_nodes()` / `get_all_edges()` 已可直接构建导出 JSON；
  `get_node_positions()` 与 `DisplayPath` 可用于校验导入后的多父级结构。
  导入时应直接调用 `LibraryService.attach_nodes()` 以复用循环检查。
- **Phase 7**：`NodePositionsDialog` 的路径列表可复用于搜索结果的位置展示；
  `ConfigManager` 可在现有基础上保存展开状态与窗口几何。
- **Phase 8**：节点删除仍只改数据库，注释/FDF 引用可继续放在 `metadata`
  或独立表中，不受本阶段关系语义影响。

---

*本报告依据 `_mds/plan.md`、`_mds/stage.md` 与 Phase 5 实际代码编写。*
