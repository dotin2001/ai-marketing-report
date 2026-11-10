import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveProject } from "../project.mjs";

const config = {
  github: {
    projectOwner: "dotin2001",
    projectNumber: 2,
    statusField: "Status",
    todoOption: "Todo",
    doneOption: "Done",
  },
};

function clientFixture({ ownerType = "user", fields } = {}) {
  const project = { id: "PROJECT_DYNAMIC", number: 2, title: "AI marketing" };
  return {
    graphql: async (_query, variables) => {
      assert.equal(variables.login, "dotin2001");
      assert.equal(variables.number, 2);
      return {
        repositoryOwner: {
          __typename: ownerType === "user" ? "User" : "Organization",
          login: "dotin2001",
          projectV2: project,
        },
      };
    },
    paginate: async ({ variables }) => {
      assert.equal(variables.projectId, "PROJECT_DYNAMIC");
      return (
        fields ?? [
          { __typename: "ProjectV2Field", id: "TITLE_DYNAMIC", name: "Title" },
          {
            __typename: "ProjectV2SingleSelectField",
            id: "STATUS_DYNAMIC",
            name: "Status",
            options: [
              { id: "TODO_DYNAMIC", name: "Todo" },
              { id: "DONE_DYNAMIC", name: "Done" },
            ],
          },
        ]
      );
    },
  };
}

for (const ownerType of ["user", "organization"]) {
  test(`resolves a ${ownerType}-owned project and dynamic field options`, async () => {
    const project = await resolveProject(clientFixture({ ownerType }), config);
    assert.equal(project.ownerType, ownerType === "user" ? "User" : "Organization");
    assert.equal(project.id, "PROJECT_DYNAMIC");
    assert.equal(project.statusField.id, "STATUS_DYNAMIC");
    assert.equal(project.todoOption.id, "TODO_DYNAMIC");
    assert.equal(project.doneOption.id, "DONE_DYNAMIC");
  });
}

for (const [name, fields, code] of [
  ["absent status", [], "status_field_resolution_failed"],
  [
    "duplicate status",
    [
      { __typename: "ProjectV2SingleSelectField", id: "1", name: "Status", options: [] },
      { __typename: "ProjectV2SingleSelectField", id: "2", name: "Status", options: [] },
    ],
    "status_field_resolution_failed",
  ],
  ["wrong field type", [{ __typename: "ProjectV2Field", id: "1", name: "Status" }], "status_field_wrong_type"],
  [
    "case-mismatched status",
    [{ __typename: "ProjectV2SingleSelectField", id: "1", name: "status", options: [] }],
    "status_field_resolution_failed",
  ],
  [
    "absent Todo",
    [{ __typename: "ProjectV2SingleSelectField", id: "1", name: "Status", options: [{ id: "d", name: "Done" }] }],
    "todo_option_resolution_failed",
  ],
  [
    "case-mismatched Done",
    [
      {
        __typename: "ProjectV2SingleSelectField",
        id: "1",
        name: "Status",
        options: [
          { id: "t", name: "Todo" },
          { id: "d", name: "done" },
        ],
      },
    ],
    "done_option_resolution_failed",
  ],
]) {
  test(`rejects ${name}`, async () => {
    await assert.rejects(
      () => resolveProject(clientFixture({ fields }), config),
      (error) => error.code === code,
    );
  });
}

test("rejects an absent project owner result", async () => {
  const client = { graphql: async () => ({ repositoryOwner: null }) };
  await assert.rejects(() => resolveProject(client, config), (error) =>
    error.code === "project_resolution_failed",
  );
});
