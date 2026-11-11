import { VerificationError } from "./errors.mjs";
import { fingerprintsEqual } from "./fingerprint.mjs";
import { assertLiveIdentity } from "./identity.mjs";

export function prepareStatusMutation({
  verification,
  verifiedFingerprints,
  currentFingerprints,
  identityInput,
  todoName,
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
  if (status === doneName) {
    return Object.freeze({ kind: "already_done", exitCode: 0, identity });
  }
  if (status !== todoName) {
    throw new VerificationError(
      "status_conflict",
      `Project item status is ${status ?? "unavailable"}; expected ${todoName} or ${doneName}.`,
      { status, todoName, doneName },
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
