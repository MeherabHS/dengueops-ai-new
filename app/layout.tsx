import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Navbar from "@/components/layout/Navbar";
import Footer from "@/components/layout/Footer";
import { PROJECT_TITLE, PROJECT_SUBTITLE, ICADHI_TRACK } from "@/lib/constants";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: PROJECT_TITLE,
    template: `%s | ${PROJECT_TITLE}`,
  },
  description: `${PROJECT_SUBTITLE}. Submitted to IEEE ICADHI — ${ICADHI_TRACK}.`,
  keywords: [
    "dengue",
    "public health",
    "decision support",
    "Dhaka",
    "Bangladesh",
    "outbreak forecasting",
    "health data analytics",
    "IEEE ICADHI",
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="scroll-smooth">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased min-h-screen flex flex-col`}>
        <Navbar />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
