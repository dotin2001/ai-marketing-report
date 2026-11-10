import { createInterface } from "node:readline/promises";

export function createTerminalPrompt({ input = process.stdin, output = process.stdout } = {}) {
  const interface_ = createInterface({ input, output, terminal: input.isTTY === true });
  return Object.freeze({
    async ask(question) {
      try {
        return await interface_.question(question);
      } catch (error) {
        if (error.code === "ERR_USE_AFTER_CLOSE" || error.name === "AbortError") return null;
        throw error;
      }
    },
    close() {
      interface_.close();
    },
  });
}

export async function selectIssue(items, { prompt, output = process.stdout } = {}) {
  if (!Array.isArray(items) || items.length === 0) {
    output.write("No eligible Todo issues exist in the configured Project.\n");
    return { kind: "no_items", exitCode: 0 };
  }
  if (!prompt || typeof prompt.ask !== "function") {
    throw new TypeError("Issue selection requires a prompt adapter.");
  }

  output.write("Eligible Todo issues:\n");
  for (const [index, item] of items.entries()) {
    output.write(`${index + 1}. #${item.issueNumber} ${item.title} — ${item.url}\n`);
  }

  for (;;) {
    const answer = await prompt.ask("Select an issue number, or q to cancel: ");
    if (answer === null || answer === undefined) {
      output.write("Selection cancelled (end of input).\n");
      return { kind: "cancelled", exitCode: 0 };
    }
    const normalized = String(answer).trim();
    if (["", "q", "quit", "cancel"].includes(normalized.toLowerCase())) {
      output.write("Selection cancelled.\n");
      return { kind: "cancelled", exitCode: 0 };
    }
    if (/^\d+$/.test(normalized)) {
      const selectedIndex = Number(normalized) - 1;
      if (selectedIndex >= 0 && selectedIndex < items.length) {
        const selected = items[selectedIndex];
        output.write(`Selected #${selected.issueNumber}: ${selected.title}\n`);
        return { kind: "selected", exitCode: 0, item: selected };
      }
    }
    output.write(`Invalid selection: ${normalized || "(empty)"}. Try again or enter q.\n`);
  }
}
