import { expect, test, type Page } from "@playwright/test";
import { PDFDocument, StandardFonts } from "pdf-lib";

async function syntheticPdf(): Promise<Buffer> {
	const document = await PDFDocument.create();
	const font = await document.embedFont(StandardFonts.Helvetica);
	for (const [index, text] of [
		"Scholens synthetic PDF first page searchable phrase",
		"Scholens synthetic PDF second page",
	].entries()) {
		const page = document.addPage([612, 792]);
		page.drawText(text, { x: 72, y: 700, size: 16, font });
		page.drawText(`Page ${index + 1}`, { x: 72, y: 72, size: 12, font });
	}
	return Buffer.from(await document.save());
}

async function mockSharedPaper(page: Page) {
	const pdf = await syntheticPdf();
	await page.route("**/synthetic.pdf", (route) =>
		route.fulfill({
			status: 200,
			contentType: "application/pdf",
			body: pdf,
			headers: { "access-control-allow-origin": "*" },
		}),
	);
	await page.route(/\/api\/public\/papers\/e2e-paper$/, (route) =>
		route.fulfill({
			headers: {
				"access-control-allow-credentials": "true",
				"access-control-allow-headers": "content-type",
				"access-control-allow-methods": "GET,OPTIONS",
				"access-control-allow-origin": "http://127.0.0.1:3100",
			},
			json: {
				document: {
					id: "00000000-0000-0000-0000-000000000001",
					original_filename: "synthetic.pdf",
					mime_type: "application/pdf",
					size_bytes: pdf.length,
					title: "Synthetic Research Paper",
					authors: ["Owner"],
					abstract: "Synthetic abstract",
					institutions: [],
					keywords: [],
					doi: null,
					journal: null,
					publisher: null,
					publish_date: null,
					summary: "A deterministic browser regression fixture.",
					summary_citations: [],
					starter_questions: [],
					processing_status: "completed",
					parser_quality: "full",
					parser_warning_code: null,
					created_at: "2026-07-28T00:00:00Z",
					updated_at: "2026-07-28T00:00:00Z",
				},
				file_url: "http://127.0.0.1:3100/synthetic.pdf",
				owner: { id: 1, display_name: "Owner" },
			},
		}),
	);
}

test("loads, searches, zooms, and changes pages in a two-page PDF", async ({
	page,
}, testInfo) => {
	test.skip(testInfo.project.name !== "chromium");
	await mockSharedPaper(page);
	await page.goto("/paper/share/e2e-paper");

	await expect(page.getByText("Synthetic Research Paper")).toBeVisible();
	await expect(page.locator(".page")).toHaveCount(2, { timeout: 20_000 });
	await page.getByRole("button", { name: "Search (Cmd+F)" }).click();
	await page.getByPlaceholder("Search...").fill("searchable phrase");
	await page.getByPlaceholder("Search...").press("Enter");
	await expect(page.getByText("1/1")).toBeVisible();
	await page.getByRole("button", { name: /zoom in/i }).click();
	await page.getByRole("button", { name: /next page/i }).click();
	await expect(page.getByText(/2\s*\/\s*2/)).toBeVisible();
});

test("mobile view can switch between reader and panel", async ({ page }) => {
	test.skip(page.viewportSize()?.width ? page.viewportSize()!.width > 600 : true);
	await mockSharedPaper(page);
	await page.goto("/paper/share/e2e-paper");

	await expect(page.locator(".page").first()).toBeVisible({ timeout: 20_000 });
	await page.getByRole("button", { name: /panel|chat|overview/i }).first().click();
	await expect(page.getByText("A deterministic browser regression fixture.")).toBeVisible();
});
