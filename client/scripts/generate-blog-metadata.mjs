import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const contentDirectory = path.join(scriptDirectory, "../src/content");
const outputPath = path.join(scriptDirectory, "../public/blog-latest.json");

function generateBlogMetadata() {
    const files = fs.readdirSync(contentDirectory).filter((file) => file.endsWith(".mdx"));
    const posts = [];

    for (const file of files) {
        const content = fs.readFileSync(path.join(contentDirectory, file), "utf-8");
        const metadataMatch = content.match(/export\s+const\s+metadata\s*=\s*(\{[\s\S]*?\});?\s*\n/);
        if (!metadataMatch) continue;

        try {
            // Blog files are repository-owned; parsing their exported metadata is a build-time step.
            const metadata = Function(`"use strict"; return (${metadataMatch[1]})`)();
            posts.push({
                slug: file.replace(".mdx", ""),
                title: metadata.title,
                description: metadata.description,
                date: metadata.date,
            });
        } catch (error) {
            console.warn(`Failed to parse metadata from ${file}:`, error.message);
        }
    }

    posts.sort((first, second) => {
        const firstDate = first.date ? new Date(first.date) : new Date(0);
        const secondDate = second.date ? new Date(second.date) : new Date(0);
        return secondDate.getTime() - firstDate.getTime();
    });

    const latestPost = posts[0] ?? null;
    fs.writeFileSync(outputPath, JSON.stringify(latestPost, null, 2));
    console.log("Generated blog-latest.json:", latestPost?.title ?? "No posts found");
}

generateBlogMetadata();
