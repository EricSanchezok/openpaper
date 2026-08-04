import { MetadataRoute } from 'next'
import { readdirSync, statSync } from 'fs'
import { join } from 'path'

export default function sitemap(): MetadataRoute.Sitemap {
    const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || "http://127.0.0.1:7303";

    // Static pages
    const staticPages = [
        {
            url: baseUrl,
            lastModified: new Date(),
            changeFrequency: 'daily' as const,
            priority: 1,
        },
    ]

    // Get blog posts dynamically
    const blogPosts = getBlogPosts().map((post) => ({
        url: `${baseUrl}/blog/${post.slug}`,
        lastModified: post.lastModified,
        changeFrequency: 'weekly' as const,
        priority: 0.7,
    }))

    return [...staticPages, ...blogPosts]
}


function getBlogPosts() {
    const contentDir = join(process.cwd(), 'src/content')
    const posts: Array<{ slug: string; lastModified: Date }> = []

    try {
        const files = readdirSync(contentDir)

        for (const file of files) {
            if (file.endsWith('.mdx')) {
                const filePath = join(contentDir, file)

                try {
                    const stats = statSync(filePath)
                    // Remove .mdx extension to get the slug
                    const slug = file.replace('.mdx', '')

                    posts.push({
                        slug,
                        lastModified: stats.mtime,
                    })
                } catch {
                    // Skip if file can't be read
                    continue
                }
            }
        }
    } catch {
        // Blog metadata is optional during static generation.
    }

    return posts
}
