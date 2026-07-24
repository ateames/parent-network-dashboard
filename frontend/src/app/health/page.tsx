import { redirect } from "next/navigation";

export default function HealthIndexPage() {
  redirect("/health/system");
}
