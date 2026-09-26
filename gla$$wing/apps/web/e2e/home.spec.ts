import { expect, test } from "@playwright/test";

test("the workspace opens on document upload", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "AI procurement control" })).toBeVisible();
  await expect(page.getByText("Upload documents")).toBeVisible();
});
