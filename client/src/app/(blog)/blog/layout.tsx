import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "../../globals.css";
import Link from "next/link";
import Image from 'next/image';

const geistSans = Geist({
    variable: "--font-geist-sans",
    subsets: ["latin"],
});

const geistMono = Geist_Mono({
    variable: "--font-geist-mono",
    subsets: ["latin"],
});

export const metadata: Metadata = {
    metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://127.0.0.1:7303"),
    title: "Scholens - Blog",
    description: "The fastest way to annotate, understand, and share your papers. Check out our blog for the latest updates and insights.",
    openGraph: {
        title: "Scholens - Blog",
        description: "The fastest way to annotate, understand, and share your papers. Check out our blog for the latest updates and insights.",
        type: "website",
    },
    twitter: {
        card: "summary",
        title: "Scholens - Blog",
        description: "The fastest way to annotate, understand, and share your papers. Check out our blog for the latest updates and insights.",
    },
};

export default function MdxLayout({ children }: { children: React.ReactNode }) {
    // Create any shared layout or styles here
    return (
        <html lang="en" suppressHydrationWarning>
            <head>
                <script
                    dangerouslySetInnerHTML={{
                        __html: `
(function() {
  try {
    var darkMode = localStorage.getItem('darkMode');
    if (darkMode === 'dark' || (!darkMode && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  } catch (e) {}
})();
                        `
                    }}
                    id="theme-script"
                />
            </head>
            <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
                <main className="container mx-auto py-8">
                    <Link href="/" className="flex items-center justify-center mb-8">
                        <Image
                            src="/scholens.svg"
                            width={48}
                            height={48}
                            alt="Scholens Logo"
                        />
                        <span className="text-2xl font-bold ml-4">Scholens</span>
                    </Link>
                    <div
                        className="mx-2 md:ml-auto md:mr-auto pb-10 prose prose-headings:mt-8 prose-headings:font-semibold prose-h1:text-5xl prose-h2:text-4xl prose-h3:text-3xl prose-h4:text-2xl prose-h5:text-xl prose-h6:text-lg dark:prose-invert">
                        {children}
                    </div>
                </main>
            </body>
        </html>

    )
}
