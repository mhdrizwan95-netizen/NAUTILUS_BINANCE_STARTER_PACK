import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DynamicParamForm } from "./DynamicParamForm";

const schema = {
  title: "Test",
  fields: [
    {
      type: "string",
      key: "name",
      label: "Name",
      placeholder: "Name",
      default: "alpha",
    },
    {
      type: "boolean",
      key: "enabled",
      label: "Enabled",
      default: true,
    },
  ],
} as const;

describe("DynamicParamForm", () => {
  it("emits onChange only when values actually change", async () => {
    const onChange = vi.fn();

    const { rerender } = render(
      <DynamicParamForm
        schema={schema}
        initial={{ name: "alpha", enabled: true }}
        onSubmit={vi.fn()}
        onChange={onChange}
      />,
    );

    // Initial emit occurs once on mount.
    expect(onChange).toHaveBeenCalledTimes(1);

    // Re-render with identical props should not trigger another emit.
    rerender(
      <DynamicParamForm
        schema={schema}
        initial={{ name: "alpha", enabled: true }}
        onSubmit={vi.fn()}
        onChange={onChange}
      />,
    );
    expect(onChange).toHaveBeenCalledTimes(1);

    // Changing an input should trigger onChange again.
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "beta" } });
    expect(onChange).toHaveBeenCalledTimes(2);
  });
});
