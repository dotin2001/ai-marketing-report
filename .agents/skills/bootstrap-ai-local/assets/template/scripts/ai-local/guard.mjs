import { VerificationError } from "./errors.mjs";
import { fingerprintsEqual } from "./fingerprint.mjs";
import { assertLiveIdentity } from "./identity.mjs";

export function prepareStatusMutation({
  verification,
  verifiedFingerprints,
  currentFingerprints,
  identityInput,
  todoName,
  inProgressName,
  doneName,
}) {
  if (verification?.kind !== "VerifiedSynchronization") {
    throw new VerificationError("verification_token_invalid", "A typed passing verification result is required.");
  }
  if (!fingerprintsEqual(verifiedFingerprints, currentFingerprints)) {
    throw new VerificationError(
      "fingerprint_changed",
      "Verification inputs changed after checks completed; synchronization was stopped.",
    );
  }
  const identity = assertLiveIdentity(identityInput);
  const status = identityInput.item.status;
  if (status === doneName && identityInput.item.statusOptionId === identityInput.project.doneOption.id) {
    return Object.freeze({ kind: "already_done", exitCode: 0, identity });
  }
  const statusOptionId = identityInput.item.statusOptionId;
  const expectedOption = status === todoName
    ? identityInput.project.todoOption
    : status === inProgressName ? identityInput.project.inProgressOption : null;
  if (!expectedOption || statusOptionId !== expectedOption.id) {
    throw new VerificationError(
      "status_conflict",
      `Project item status is ${status ?? "unavailable"}; expected ${todoName}, ${inProgressName}, or ${doneName}.`,
      { status, todoName, inProgressName, doneName },
    );
  }
  return Object.freeze({
    kind: "ReadyStatusMutation",
    identity,
    projectId: identityInput.project.id,
    projectItemId: identityInput.item.projectItemId,
    statusFieldId: identityInput.project.statusField.id,
    doneOptionId: identityInput.project.doneOption.id,
    doneName,
  });
}

export async function executeAfterFinalGuard(options, mutate) {
  const guarded = prepareStatusMutation(options);
  if (guarded.kind === "already_done") return guarded;
  return mutate(guarded);
}
