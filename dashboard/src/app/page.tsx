import { redirect } from "next/navigation";

/**
 * Root page redirects to the positions view (the primary dashboard page).
 */
export default function Home() {
  redirect("/positions");
}
