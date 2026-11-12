import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FoundationPage from "@/app/page";

describe("foundation page", () => {
  it("renders the setup state without contacting a backend", () => {
    render(<FoundationPage />);

    expect(
      screen.getByRole("heading", { name: "AI Marketing Report Assistant" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Foundation ready")).toBeInTheDocument();
    expect(screen.getByText("Health-ready")).toBeInTheDocument();
  });
});

