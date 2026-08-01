"""Regression contract for lane TOML serialization and name validation."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

import pytest
from gr2.prototypes import lane_workspace_prototype
from gr2.prototypes.lane_workspace_prototype import (
    SCRATCHPAD_SCHEMA_VERSION,
    SharedScratchpad,
    create_continuation_lane,
    create_lane,
    create_review_lane,
    create_shared_scratchpad,
    lane_file,
    load_lane_doc,
)


def _workspace(
    tmp_path: Path,
    *,
    owner_unit: str = "atlas",
    additional_units: tuple[str, ...] = (),
) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / ".grip").mkdir(parents=True)
    (workspace / "agents").mkdir()
    units = "".join(
        f'''\n[[units]]
name = "{unit}"
path = "agents/{index}"
repos = ["app"]
'''
        for index, unit in enumerate(additional_units, start=2)
    )
    (workspace / ".grip" / "workspace_spec.toml").write_text(
        f'''schema_version = 1
workspace_name = "serialization-contract"

[[repos]]
name = "app"
path = "repos/app"
url = "https://example.invalid/app.git"

[[units]]
name = "{owner_unit}"
path = "agents/unit"
repos = ["app"]
{units}''',
        encoding="utf-8",
    )
    return workspace


def _create_args(
    workspace: Path, lane_name: str, *, owner_unit: str = "atlas"
) -> argparse.Namespace:
    return argparse.Namespace(
        workspace_root=workspace,
        owner_unit=owner_unit,
        lane_name=lane_name,
        type="feature",
        repos="app",
        branch="app=feat/serialization",
        source="test",
        default_commands=["python -c 'print(\"ready\")'"],
    )


@pytest.mark.parametrize(
    "lane_name",
    [
        'quote-"lane',
        'key = "value"',
        "[new_table]",
        "hash#lane",
    ],
)
def test_structured_lane_names_roundtrip_through_real_creation(
    tmp_path: Path, lane_name: str
) -> None:
    workspace = _workspace(tmp_path)

    assert create_lane(_create_args(workspace, lane_name)) == 0

    assert load_lane_doc(workspace, "atlas", lane_name)["lane_name"] == lane_name


@pytest.mark.parametrize(
    "lane_name",
    [
        "",
        ".",
        "..",
        " leading",
        "trailing ",
        "slash/name",
        "back\\slash",
        "line\nbreak",
        "😀" * 64,
        "\ud800",
    ],
)
def test_invalid_path_component_is_rejected_before_any_lane_tree_is_written(
    tmp_path: Path, lane_name: str
) -> None:
    workspace = _workspace(tmp_path)
    before = sorted(path.relative_to(workspace) for path in workspace.rglob("*"))

    with pytest.raises(SystemExit, match="invalid lane_name"):
        create_lane(_create_args(workspace, lane_name))

    after = sorted(path.relative_to(workspace) for path in workspace.rglob("*"))
    assert after == before


def test_invalid_owner_unit_is_rejected_before_any_lane_tree_is_written(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, owner_unit=" atlas")
    before = sorted(path.relative_to(workspace) for path in workspace.rglob("*"))

    with pytest.raises(SystemExit, match="invalid owner_unit"):
        create_lane(_create_args(workspace, "feature", owner_unit=" atlas"))

    after = sorted(path.relative_to(workspace) for path in workspace.rglob("*"))
    assert after == before


@pytest.mark.parametrize(
    ("owner_unit", "lane_name", "message"),
    [("atlas", "..", "invalid lane_name"), ("..", "review", "invalid owner_unit")],
)
def test_review_lane_rejects_path_escape_before_touching_existing_target(
    tmp_path: Path, owner_unit: str, lane_name: str, message: str
) -> None:
    workspace = _workspace(tmp_path)
    target = lane_file(workspace, owner_unit, lane_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    original = 'lane_type = "review"\nrepos = ["app"]\npr_associations = []\n'
    target.write_text(original)

    with pytest.raises(SystemExit, match=message):
        create_review_lane(
            argparse.Namespace(
                workspace_root=workspace,
                owner_unit=owner_unit,
                repo="app",
                pr_number=41,
                lane_name=lane_name,
                branch="pr/41",
            )
        )

    assert target.read_text() == original


def test_review_lane_rewrite_uses_serializer_and_preserves_associations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    serialized_documents: list[dict[str, object]] = []
    real_serialize = lane_workspace_prototype.serialize_toml

    def record_serialize(document: dict[str, object]) -> str:
        serialized_documents.append(document)
        return real_serialize(document)

    monkeypatch.setattr(lane_workspace_prototype, "serialize_toml", record_serialize)

    for pr_number in (41, 42):
        assert (
            create_review_lane(
                argparse.Namespace(
                    workspace_root=workspace,
                    owner_unit="atlas",
                    repo="app",
                    pr_number=pr_number,
                    lane_name='review-"shared',
                    branch="pr/shared",
                )
            )
            == 0
        )

    doc = load_lane_doc(workspace, "atlas", 'review-"shared')
    assert [item["ref"] for item in doc["pr_associations"]] == ["app#41", "app#42"]
    assert [
        [item["ref"] for item in document["pr_associations"]]
        for document in serialized_documents
    ] == [["app#41"], ["app#41", "app#42"]]


@pytest.mark.parametrize(
    ("target_unit", "target_lane_name", "message"),
    [
        ("apollo", "../../escaped", "invalid target_lane_name"),
        ("..", "next", "invalid target_unit"),
    ],
)
def test_continuation_rejects_invalid_target_components_before_writing(
    tmp_path: Path, target_unit: str, target_lane_name: str, message: str
) -> None:
    workspace = _workspace(tmp_path, additional_units=("apollo", ".."))
    assert create_lane(_create_args(workspace, "source")) == 0
    before = sorted(path.relative_to(workspace) for path in workspace.rglob("*"))

    with pytest.raises(SystemExit, match=message):
        create_continuation_lane(
            argparse.Namespace(
                workspace_root=workspace,
                source_owner_unit="atlas",
                source_lane_name="source",
                target_unit=target_unit,
                target_lane_name=target_lane_name,
            )
        )

    after = sorted(path.relative_to(workspace) for path in workspace.rglob("*"))
    assert after == before


def test_shared_scratchpad_rejects_invalid_name_before_writing(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    before = sorted(path.relative_to(workspace) for path in workspace.rglob("*"))

    with pytest.raises(SystemExit, match="invalid name"):
        create_shared_scratchpad(
            argparse.Namespace(
                workspace_root=workspace,
                name="../../escaped",
                kind="doc",
                purpose="serialization contract",
                participant=[],
                ref=[],
                source="test",
            )
        )

    after = sorted(path.relative_to(workspace) for path in workspace.rglob("*"))
    assert after == before


def test_shared_scratchpad_roundtrips_toml_significant_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serialized_documents: list[dict[str, object]] = []
    real_serialize = lane_workspace_prototype.serialize_toml

    def record_serialize(document: dict[str, object]) -> str:
        serialized_documents.append(document)
        return real_serialize(document)

    monkeypatch.setattr(lane_workspace_prototype, "serialize_toml", record_serialize)
    scratchpad = SharedScratchpad(
        schema_version=SCRATCHPAD_SCHEMA_VERSION,
        name='notes-"shared',
        kind="key = value",
        purpose="[structured] # context",
        participants=['atlas"one', "apollo#two"],
        linked_refs=['app#41', 'key = "value"'],
        lifecycle="draft",
        creation_source="test",
        docs_root='shared/notes-"shared/docs',
        notes_root="shared/notes#shared/notes",
        context_root="shared/[notes]/context",
        created_at="2026-08-01T00:00:00Z",
        updated_at="2026-08-01T00:00:00Z",
    )

    document = tomllib.loads(scratchpad.as_toml())

    assert document["name"] == scratchpad.name
    assert document["kind"] == scratchpad.kind
    assert document["purpose"] == scratchpad.purpose
    assert document["participants"] == scratchpad.participants
    assert document["linked_refs"] == scratchpad.linked_refs
    assert document["paths"] == {
        "docs_root": scratchpad.docs_root,
        "notes_root": scratchpad.notes_root,
        "context_root": scratchpad.context_root,
    }
    assert serialized_documents == [document]
