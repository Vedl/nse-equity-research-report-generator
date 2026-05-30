import Link from "next/link"
import { Home } from "lucide-react"
import { buttonVariants } from "@/components/ui/button"

export default function NotFound() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center gap-4 text-center px-4">
      <p className="font-mono text-6xl font-bold text-muted-foreground/20">404</p>
      <h1 className="text-2xl font-bold">Page not found</h1>
      <p className="max-w-sm text-muted-foreground">
        The page you&apos;re looking for doesn&apos;t exist. Try searching for a
        Nifty 500 company on the home page.
      </p>
      <Link href="/" className={buttonVariants({ variant: "default" }) + " gap-2"}>
        <Home className="h-4 w-4" />
        Go home
      </Link>
    </div>
  )
}
