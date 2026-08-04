import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "../../globals.css";
import { AppSidebar } from "@/components/sidebar/AppSidebar";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { AuthProvider } from "@/lib/auth";

import { Toaster } from "@/components/ui/sonner";
import { PostHogProvider, ThemeProvider } from "@/lib/providers";
import { SharePaperButton } from '@/components/SharePaperButton';

import { SidebarController } from "@/components/utils/SidebarAutoCollapse";
import Image from "next/image";
import Link from "next/link";
import { ManageProjectsButton } from "@/components/ManageProjectsButton";
import { MobilePaperMenu } from "@/components/MobilePaperMenu";
import { CitePaperButton } from "@/components/CitePaperButton";
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
				<ThemeProvider>
					<AuthProvider>
						<PostHogProvider>
							<SidebarProvider>
								<AppSidebar />
								<SidebarInset>
									<header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
										<SidebarTrigger className="-ml-1" />
										<Separator orientation="vertical" className="mr-2 h-4" />
										<Link href="/" className="flex flex-1 items-center gap-2 hover:opacity-80 transition-opacity">
											<Image
												src="/scholens.svg"
												width={24}
												height={24}
												alt="Scholens Logo"
											/>
											<span className="text-sm font-semibold">Scholens</span>
										</Link>
									{/* Desktop buttons */}
								<div className="hidden md:flex items-center gap-2">
									<ManageProjectsButton />
									<CitePaperButton />
									<SharePaperButton />
								</div>
									{/* Mobile menu */}
									<MobilePaperMenu />
									</header>
									<SidebarController>
										{children}
									</SidebarController>
								</SidebarInset>
							</SidebarProvider>
						</PostHogProvider>
					</AuthProvider>
				</ThemeProvider>
				<Toaster
					position="top-right"
					richColors
					duration={3000}
				/>
			</body>
		</html>
	);
}
