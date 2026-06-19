"use client";
import ResourceCrud from "../../../components/ResourceCrud";
import { RESOURCES } from "../../../lib/resources";

export default function Page() {
  return <ResourceCrud config={RESOURCES.contratos} />;
}
