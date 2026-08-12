/**
 * Convenience aliases over OpenAPI-generated schemas.
 * Regenerate with `make openapi` (do not hand-edit generated files).
 *
 * FastAPI/Pydantic version drift can emit either `Foo` or `Foo-Output` for the
 * same response model. PreferOutput picks the serialization schema when present
 * so local and Docker-pinned exports both typecheck.
 */

import type { components } from "@/generated/openapi";

type Schemas = components["schemas"];

/** Response schema: `Name-Output` (newer Pydantic) or `Name` (pinned Docker deps). */
type PreferOutput<Name extends string> =
  `${Name}-Output` extends keyof Schemas
    ? Schemas[Extract<`${Name}-Output`, keyof Schemas>]
    : Name extends keyof Schemas
      ? Schemas[Name]
      : never;

export type DashboardSummary = components["schemas"]["DashboardSummaryOut"];
export type AttentionItem = components["schemas"]["AttentionItemOut"];
export type ActiveChild = components["schemas"]["ActiveChildOut"];
export type DashboardDevice = components["schemas"]["DashboardDeviceOut"];
export type RecentActivityItem = components["schemas"]["RecentActivityItemOut"];
export type FindingsBySeverity = components["schemas"]["FindingsBySeverityOut"];
export type DataHealthSource = components["schemas"]["DataHealthSourceOut"];
export type IngestSource = components["schemas"]["IngestSource"];
export type SourceHealthStatus = components["schemas"]["SourceHealthStatus"];
export type StreamEvent = components["schemas"]["StreamEventOut"];
export type StreamEventList = components["schemas"]["StreamEventListOut"];
export type StreamEventKind = components["schemas"]["StreamEventKind"];
export type FindingSeverity = components["schemas"]["FindingSeverity"];

export type PersonOut = components["schemas"]["PersonOut"];
export type PersonListOut = components["schemas"]["PersonListOut"];
export type PersonCreateIn = components["schemas"]["PersonCreateIn"];
export type PersonPatchIn = components["schemas"]["PersonPatchIn"];
export type PersonDeviceAssignIn = components["schemas"]["PersonDeviceAssignIn"];
export type PersonDeviceOut = components["schemas"]["PersonDeviceOut"];
export type AssignedDeviceOut = components["schemas"]["AssignedDeviceOut"];
export type PersonRole = components["schemas"]["PersonRole"];

export type DeviceSummaryOut = components["schemas"]["DeviceSummaryOut"];
export type DeviceListOut = components["schemas"]["DeviceListOut"];
export type DeviceDetailOut = components["schemas"]["DeviceDetailOut"];
export type DevicePatchIn = components["schemas"]["DevicePatchIn"];
export type AssignedPersonOut = components["schemas"]["AssignedPersonOut"];
export type DeviceIdentifierOut = PreferOutput<"DeviceIdentifierOut">;
export type IpAssignmentOut = components["schemas"]["IpAssignmentOut"];
export type IdentifierKind = components["schemas"]["IdentifierKind"];
export type InternetRestrictionOut =
  components["schemas"]["InternetRestrictionOut"];
export type InternetRestrictionCreateIn =
  components["schemas"]["InternetRestrictionCreateIn"];
export type RestrictionStatus = components["schemas"]["RestrictionStatus"];

export type ActivitySummaryOut = components["schemas"]["ActivitySummaryOut"];
export type DeviationOut = components["schemas"]["DeviationOut"];
export type BaselineOut = components["schemas"]["BaselineOut"];
export type MetricBaselineOut = components["schemas"]["MetricBaselineOut"];

export type FindingOut = components["schemas"]["FindingOut"];
export type FindingListOut = components["schemas"]["FindingListOut"];
export type FindingStatus = components["schemas"]["FindingStatus"];
export type FindingConfidence = components["schemas"]["FindingConfidence"];
export type FindingFeedbackClassification =
  components["schemas"]["FindingFeedbackClassification"];
export type FindingFeedbackIn = components["schemas"]["FindingFeedbackIn"];
export type FindingFeedbackOut = components["schemas"]["FindingFeedbackOut"];
export type SuppressionOut = components["schemas"]["SuppressionOut"];
export type SuppressionListOut = components["schemas"]["SuppressionListOut"];

export type CorrelationStatus = components["schemas"]["CorrelationStatus"];
export type CandidateDeviceOut = components["schemas"]["CandidateDeviceOut"];
export type ReviewItemOut = PreferOutput<"ReviewItemOut">;
export type ReviewListOut = components["schemas"]["ReviewListOut"];
export type CorrelationResolveIn =
  components["schemas"]["CorrelationResolveIn"];
export type CorrelationResolveOut =
  components["schemas"]["CorrelationResolveOut"];

export type SourceHealthOut = components["schemas"]["SourceHealthOut"];
export type SourceHealthListOut = components["schemas"]["SourceHealthListOut"];

export type SystemHealthOut = components["schemas"]["SystemHealthOut"];
export type WorkerHealthOut = components["schemas"]["WorkerHealthOut"];
export type LastBatchOut = components["schemas"]["LastBatchOut"];
export type SourceErrorCountOut = components["schemas"]["SourceErrorCountOut"];
export type ComponentStatusOut = components["schemas"]["ComponentStatusOut"];

export type ThresholdsOut = components["schemas"]["ThresholdsOut"];
export type ThresholdsPatchIn = components["schemas"]["ThresholdsPatchIn"];
export type LocalSettingsOut = components["schemas"]["LocalSettingsOut"];
export type ExpectedActivityScheduleOut =
  components["schemas"]["ExpectedActivityScheduleOut"];
export type ExpectedActivityScheduleIn =
  components["schemas"]["ExpectedActivityScheduleIn"];
export type ExpectedActivitySchedulePatchIn =
  components["schemas"]["ExpectedActivitySchedulePatchIn"];
export type ExpectedActivityScheduleListOut =
  components["schemas"]["ExpectedActivityScheduleListOut"];
export type IngestBatchStatus = components["schemas"]["IngestBatchStatus"];

export type ConnectionsOut = components["schemas"]["ConnectionsOut"];
export type ConnectionsPutIn = components["schemas"]["ConnectionsPutIn"];
export type ConnectionTestIn = components["schemas"]["ConnectionTestIn"];
export type ConnectionTestOut = components["schemas"]["ConnectionTestOut"];
export type SetupStatusOut = components["schemas"]["SetupStatusOut"];
export type DashboardVerifyIn = components["schemas"]["DashboardVerifyIn"];
export type DashboardVerifyOut = components["schemas"]["DashboardVerifyOut"];
