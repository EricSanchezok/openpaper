import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from "sonner";
import "../globals.css";

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
	title: "Scholens",
	description: "The fastest way to annotate and deeply understand research papers.",
	icons: {
		icon: "/icon.svg"
	},
	openGraph: {
		title: "Scholens",
		description: "The fastest way to annotate and deeply understand research papers.",
		type: "website",
	},
	twitter: {
		card: "summary",
		title: "Scholens",
		description: "The fastest way to annotate and deeply understand your research papers.",
	},
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="en" suppressHydrationWarning>
			<head>
				<script
					id="theme-script"
					dangerouslySetInnerHTML={{
						__html: `
      try {
        if (localStorage.getItem('darkMode') === 'dark' ||
            (!localStorage.getItem('darkMode') && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
          document.documentElement.classList.add('dark');
        } else {
          document.documentElement.classList.remove('dark');
        }
      } catch (e) {}
    `,
					}}
				/>
			</head>
			<body
				className={`${geistSans.variable} ${geistMono.variable} antialiased`}
			>
				{children}
				<Toaster position="top-right" richColors duration={10000} />
			</body>
		</html>
	);
}
