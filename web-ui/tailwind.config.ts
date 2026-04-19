import type { Config } from "tailwindcss";

const config: Config = {
    darkMode: "class",
    content: [
        "./pages/**/*.{js,ts,jsx,tsx,mdx}",
        "./components/**/*.{js,ts,jsx,tsx,mdx}",
        "./app/**/*.{js,ts,jsx,tsx,mdx}",
    ],
    theme: {
        extend: {
            colors: {
                primary: {
                    DEFAULT: "#137fec",
                    50: "#eff6ff",
                    100: "#dbeafe",
                    200: "#bfdbfe",
                    300: "#93c5fd",
                    400: "#60a5fa",
                    500: "#137fec",
                    600: "#1165c4",
                    700: "#104b9c",
                    800: "#0e3874",
                    900: "#0c254c",
                },
                background: "hsl(222, 47%, 11%)",
                foreground: "hsl(210, 40%, 98%)",
                card: {
                    DEFAULT: "hsl(222, 47%, 15%)",
                    foreground: "hsl(210, 40%, 98%)",
                },
                muted: {
                    DEFAULT: "hsl(217, 33%, 17%)",
                    foreground: "hsl(215, 20%, 65%)",
                },
                border: "hsl(217, 33%, 25%)",
                input: "hsl(217, 33%, 25%)",
                ring: "#137fec",
            },
            borderRadius: {
                lg: "0.75rem",
                md: "0.5rem",
                sm: "0.25rem",
            },
        },
    },
    plugins: [],
};
export default config;
