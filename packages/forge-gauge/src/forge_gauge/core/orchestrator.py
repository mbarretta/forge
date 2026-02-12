"""
Orchestrates the main workflow for Gauge - Container Vulnerability Assessment Tool.
"""
import csv
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from forge_gauge.common import OUTPUT_CONFIGS, GitHubAuthValidator
from forge_gauge.constants import __version__
from forge_gauge.core.cache import ScanCache
from forge_gauge.core.models import ImagePair
from forge_gauge.utils.issue_matcher import search_github_issues_for_images, log_issue_search_results, IssueMatchResult
from forge_gauge.utils.image_matcher import MatchResult
from forge_gauge.commands.match import write_summary_csv
from forge_gauge.core.scanner import VulnerabilityScanner
from forge_gauge.integrations.kev_catalog import KEVCatalog
from forge_gauge.outputs.config import HTMLGeneratorConfig, XLSXGeneratorConfig
from forge_gauge.outputs.html_generator import HTMLGenerator
from forge_gauge.outputs.xlsx_generator import XLSXGenerator
from forge_gauge.utils.docker_utils import DockerClient
from forge_gauge.utils.filename_utils import sanitize_customer_name
from forge_gauge.utils.logging_helpers import log_error_section, log_warning_section
from forge_gauge.utils.console import print_header, print_success, print_error, print_info, prompt_yes_no

logger = logging.getLogger(__name__)


class GaugeOrchestrator:
    """
    Orchestrates the Gauge workflow from image loading to report generation.
    """

    def __init__(self, args):
        """
        Initialize the orchestrator with parsed command-line arguments.

        Args:
            args: Parsed arguments from argparse.
        """
        self.args = args
        self.docker_client = None
        self.cache = None
        self.kev_catalog = None
        self.scanner = None
        self.results = []
        self.pairs = []
        self._logged_in_as_support = False  # Track if we need to restore identity

    def run(self):
        """
        Execute the main Gauge workflow.
        """
        try:
            self._run_workflow()
        finally:
            # Always restore identity if we logged in as support
            self._restore_identity_if_needed()

    def _run_workflow(self):
        """Execute the main workflow steps."""
        logger.info(f"Gauge - Container Vulnerability Assessment v{__version__}")
        logger.info("=" * 60)

        # Parse output types
        try:
            output_types = self.parse_output_types(self.args.output)
        except ValueError as e:
            logger.error(f"Invalid output specification: {e}")
            sys.exit(1)

        # Build output description from OUTPUT_CONFIGS
        output_names = {}
        for output_type, config in OUTPUT_CONFIGS.items():
            output_names[output_type] = config["description"]
            # Add format-specific descriptions for multi-format outputs
            if "formats" in config:
                for format_key, format_config in config["formats"].items():
                    output_names[f"{output_type}_{format_key}"] = format_config["description"]

        output_list = [output_names[t] for t in sorted(output_types)]
        logger.info(f"Output types: {', '.join(output_list)}")

        # Load image pairs
        self.pairs = self._load_image_pairs()

        # Initialize components
        self._initialize_components()

        # Validate GitHub authentication if pricing output requested
        if "pricing" in output_types:
            validator = GitHubAuthValidator(self.args.pricing_policy)
            validator.validate()

        # Initialize scanner
        # Enable organization_mode if --organization was used, which enables
        # chainguard-private fallback for Chainguard images
        is_organization_mode = (
            hasattr(self.args, 'organization') and self.args.organization is not None
        )
        self.scanner = VulnerabilityScanner(
            cache=self.cache,
            docker_client=self.docker_client,
            max_workers=self.args.max_workers,
            platform=self.args.platform,
            check_fresh_images=not self.args.no_fresh_check,
            with_chps=self.args.with_chps,
            chps_max_workers=self.args.chps_max_workers,
            kev_catalog=self.kev_catalog,
            organization_mode=is_organization_mode,
        )

        # Execute scans
        self.results = self._execute_scans()

        # Show cache summary
        logger.info(self.cache.summary())

        # Check for successful results
        successful_count = sum(1 for r in self.results if r.scan_successful)
        if successful_count == 0:
            log_error_section(
                "No successful scan results to generate reports.",
                [
                    "All image scans failed. Common causes:",
                    "  - Chainguard images require authentication (run: chainctl auth configure-docker)",
                    "  - Network connectivity issues",
                    "  - Invalid image names in CSV",
                    "Check the error messages above for details.",
                ],
                logger=logger,
            )
            sys.exit(1)

        # Sanitize customer name
        safe_customer_name = sanitize_customer_name(self.args.customer_name)

        # Generate reports
        output_files = self._generate_reports(safe_customer_name, output_types)

        # Summary
        successful = sum(1 for r in self.results if r.scan_successful)
        failed = len(self.results) - successful

        logger.info("=" * 60)
        logger.info("Reports generated:")
        for output_type, file_path in output_files.items():
            logger.info(f"  - {output_names[output_type]}: {file_path}")
        logger.info(f"Scanned: {successful} successful, {failed} failed")
        logger.info("Done!")

    def parse_output_types(self, output_arg: Optional[str]) -> set[str]:
        """Parse comma-delimited output types argument."""
        valid_types = set(OUTPUT_CONFIGS.keys())
        if output_arg is None:
            return {'vuln_summary', 'cost_analysis'}
        requested_types = {t.strip() for t in output_arg.split(",")}
        # Handle 'both' as an alias for vuln_summary and cost_analysis
        if 'both' in requested_types:
            requested_types.discard('both')
            requested_types.add('vuln_summary')
            requested_types.add('cost_analysis')
        invalid_types = requested_types - valid_types
        if invalid_types:
            raise ValueError(
                f"Invalid output type(s): {', '.join(invalid_types)}. "
                f"Valid types: {', '.join(valid_types)}, both"
            )
        if not requested_types:
            raise ValueError("At least one output type must be specified")
        return requested_types

    def _initialize_components(self):
        """Initialize Docker client, cache, and KEV catalog."""
        # Check if we're in organization mode and running as support identity
        support_mode_org = None
        is_org_mode = hasattr(self.args, 'organization') and self.args.organization is not None

        if is_org_mode:
            from integrations.organization_loader import (
                is_support_identity,
                has_org_pull_access,
                get_support_identity_id,
                login_as_support,
            )

            if is_support_identity():
                support_mode_org = self.args.organization
                logger.info(
                    f"Support identity detected - will pull from chainguard-private for '{support_mode_org}'"
                )
            elif has_org_pull_access(self.args.organization):
                # User has direct access to the org registry, no support mode needed
                logger.debug(f"User has pull access to '{self.args.organization}'")
            else:
                # User doesn't have org access - check if support identity exists and offer to use it
                logger.info(f"No direct pull access to '{self.args.organization}' registry")
                support_id = get_support_identity_id(self.args.organization)
                if support_id:
                    self._offer_support_login(self.args.organization, login_as_support)
                    # Re-check if we're now in support mode
                    if is_support_identity():
                        support_mode_org = self.args.organization

        try:
            self.docker_client = DockerClient(support_mode_org=support_mode_org)
        except RuntimeError as e:
            logger.error(f"Docker/Podman not available: {e}")
            sys.exit(1)

        self.cache = ScanCache(
            cache_dir=self.args.cache_dir,
            enabled=not self.args.no_cache,
        )

        if self.args.clear_cache:
            logger.info("Clearing cache...")
            self.cache.clear()

        if not self.docker_client.ensure_chainguard_auth():
            log_error_section(
                "Failed to authenticate to Chainguard registry.",
                [
                    "Please run these commands:",
                    "  chainctl auth login",
                    "  chainctl auth configure-docker",
                    "",
                    "This sets up Docker authentication which works for both local and container execution.",
                ],
                logger=logger,
            )
            sys.exit(1)

        # Check if GCR auth is needed based on input images
        if not getattr(self.args, 'no_gcr_auth', False):
            self._ensure_gcr_auth_if_needed()

        if self.args.with_kevs:
            logger.info("KEV checking enabled, loading CISA KEV catalog...")
            self.kev_catalog = KEVCatalog()
            self.kev_catalog.load()

    def _offer_support_login(self, organization: str, login_func) -> None:
        """
        Offer to login as support identity for the organization.

        Args:
            organization: Organization name
            login_func: Function to call to perform the login
        """
        print_header(f"Support identity available for '{organization}'")
        print_info("\nYou are not currently logged in as a support user.")
        print_info("As a support user, you can pull Chainguard images directly")
        print_info("from cgr.dev/chainguard-private/ without org registry access.")
        print_info("\nWould you like gauge to log you in as the support identity")
        print_info("for this run? (Your normal identity will be restored after)")
        print()

        if prompt_yes_no("Login as support?", default=False):
            if login_func(organization):
                self._logged_in_as_support = True
                print_success("Logged in as support identity\n")
            else:
                print_error("Failed to login as support, continuing with normal identity\n")
        else:
            print_info("Continuing with normal identity\n")

    def _restore_identity_if_needed(self) -> None:
        """Restore normal identity if we logged in as support."""
        if self._logged_in_as_support:
            from integrations.organization_loader import restore_normal_identity
            print_header("Restoring normal identity...")
            print()
            if restore_normal_identity():
                print_success("Normal identity restored")
            else:
                print_error("Failed to restore normal identity")
                print_info("  Run 'chainctl auth logout && chainctl auth login' manually")

    def _ensure_gcr_auth_if_needed(self):
        """Configure GCR auth if any input images are from gcr.io."""
        from utils.gcr_auth import GCRAuthenticator

        # Collect all images from pairs
        all_images = [p.alternative_image for p in self.pairs] + \
                     [p.chainguard_image for p in self.pairs]

        gcr_credentials = getattr(self.args, 'gcr_credentials', None)
        gcr_auth = GCRAuthenticator(credentials_file=gcr_credentials)
        gcr_images = [img for img in all_images if gcr_auth.is_gcr_registry(img)]

        if gcr_images:
            logger.info(f"Detected {len(gcr_images)} GCR images, configuring authentication...")
            if gcr_auth.authenticate():
                logger.info("GCR authentication configured successfully")
            else:
                log_warning_section(
                    f"No GCR credentials found for {len(gcr_images)} gcr.io images.",
                    [
                        "Image pulls may fail. To configure GCR authentication:",
                        "  1. --gcr-credentials /path/to/service-account.json",
                        "  2. Set GOOGLE_APPLICATION_CREDENTIALS environment variable",
                        "  3. Run: gcloud auth login && gcloud auth configure-docker",
                    ],
                    logger=logger,
                )

    def _load_image_pairs(self) -> list[ImagePair]:
        """Load image pairs from CSV file, single image, or organization."""
        from utils.validation import looks_like_image_reference

        # Validate mutual exclusivity of input sources
        has_input = hasattr(self.args, 'input') and self.args.input is not None
        has_org = hasattr(self.args, 'organization') and self.args.organization is not None

        if has_input and has_org:
            logger.error("Cannot use both --input and --organization. Choose one:")
            logger.error("  --input FILE        Scan images from a CSV file")
            logger.error("  --input IMAGE       Scan a single image (e.g., nginx:latest)")
            logger.error("  --organization ORG  Scan all entitled images in a Chainguard organization")
            sys.exit(1)

        # Organization mode
        if has_org:
            return self._load_from_organization()

        # Check if input looks like an image reference rather than a file path
        if has_input:
            input_str = str(self.args.input)
            if looks_like_image_reference(input_str):
                logger.info(f"Detected single image input: {input_str}")
                return self._load_from_single_image(input_str)

        # Default to CSV mode (with default path if not specified)
        if not has_input:
            self.args.input = "images.csv"

        # Convert to Path for file operations
        self.args.input = Path(self.args.input)
        return self._load_from_csv()

    def _load_from_organization(self) -> list[ImagePair]:
        """Load image pairs from a Chainguard organization."""
        logger.info(f"Loading images from organization: {self.args.organization}")

        from integrations.organization_loader import OrganizationImageLoader

        loader = OrganizationImageLoader(
            organization=self.args.organization,
            cache_dir=self.args.cache_dir,
            github_token=getattr(self.args, 'github_token', None),
        )

        try:
            pairs = loader.load_image_pairs()
        except RuntimeError as e:
            logger.error(f"Failed to load from organization: {e}")
            sys.exit(1)

        if not pairs:
            logger.error("No valid image pairs found in organization")
            logger.error("Images may be missing metadata.yaml or aliases in the images-private repo.")
            sys.exit(1)

        logger.info(f"Loaded {len(pairs)} image pairs from organization")
        return pairs

    def _load_from_csv(self) -> list[ImagePair]:
        """Load image pairs from CSV file with validation."""
        try:
            is_single_column = self._detect_csv_format(self.args.input)
            if is_single_column:
                logger.info("Detected single-column CSV - will auto-match Chainguard images")
                images = self._parse_single_column_csv(self.args.input)
                if images:
                    logger.info(f"Auto-matching {len(images)} images to Chainguard equivalents...")
                    matcher = self._initialize_image_matcher()
                    pairs, _ = self._auto_match_images(images, matcher)
                else:
                    pairs = []
            else:
                pairs = self._parse_two_column_csv(self.args.input)
        except FileNotFoundError:
            if self.args.input == Path("images.csv"):
                logger.error("The default 'images.csv' was not found in the current directory.")
                logger.error("Run again using '--input <your-csv-file>' to specify your input file.")
            else:
                logger.error(f"Input file not found: {self.args.input}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error reading source file: {e}")
            sys.exit(1)

        if not pairs:
            logger.error("No valid image pairs found in source file")
            sys.exit(1)

        logger.info(f"Loaded {len(pairs)} image pairs")
        return pairs

    def _load_from_single_image(self, image: str) -> list[ImagePair]:
        """Load image pair from a single image reference.

        Args:
            image: Single image reference to scan

        Returns:
            List containing a single ImagePair (after auto-matching)
        """
        from core.exceptions import ValidationException
        from utils.validation import validate_image_reference

        # Validate the image reference
        try:
            image = validate_image_reference(image, "input image")
        except ValidationException as e:
            logger.error(f"Invalid image reference: {e}")
            sys.exit(1)

        # Auto-match to find Chainguard equivalent
        logger.info(f"Auto-matching {image} to Chainguard equivalent...")
        matcher = self._initialize_image_matcher()
        pairs, unmatched = self._auto_match_images([image], matcher)

        if not pairs:
            logger.error(f"Could not find a Chainguard equivalent for: {image}")
            logger.error("Try specifying the Chainguard image explicitly with a two-column CSV file.")
            sys.exit(1)

        return pairs

    def _detect_csv_format(self, csv_path: Path) -> bool:
        """Detect if CSV is single-column or two-column format."""
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if row and any(cell.strip() for cell in row):
                    if row[0].strip().startswith('#'):
                        continue
                    if any(header in row[0].lower() for header in ["chainguard", "customer", "image", "alternative"]):
                        continue
                    return len(row) == 1
        return False

    def _parse_two_column_csv(self, csv_path: Path) -> list[ImagePair]:
        """Parse two-column CSV format."""
        from core.exceptions import ValidationException
        from utils.validation import validate_image_reference
        pairs = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for line_num, row in enumerate(reader, 1):
                if not row or not any(cell.strip() for cell in row) or row[0].strip().startswith('#'):
                    continue
                if line_num == 1 and any(h in row[0].lower() for h in ["chainguard", "customer", "image", "alternative"]):
                    continue
                if len(row) < 2:
                    logger.warning(f"Line {line_num}: insufficient columns, skipping")
                    continue
                alt_image, cg_image = row[0].strip(), row[1].strip()
                if not alt_image or not cg_image:
                    logger.warning(f"Line {line_num}: empty image reference, skipping")
                    continue
                try:
                    alt_image = validate_image_reference(alt_image, f"alternative_image (line {line_num})")
                    cg_image = validate_image_reference(cg_image, f"chainguard_image (line {line_num})")
                    if alt_image == cg_image:
                        logger.warning(f"Line {line_num}: images are identical, skipping")
                        continue
                    pairs.append(ImagePair(cg_image, alt_image))
                except ValidationException as e:
                    logger.error(f"Validation error: {e}")
                    sys.exit(1)
        return pairs

    def _parse_single_column_csv(self, csv_path: Path) -> list[str]:
        """Parse single-column CSV format."""
        from core.exceptions import ValidationException
        from utils.validation import validate_image_reference
        images = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for line_num, row in enumerate(reader, 1):
                if not row or not any(cell.strip() for cell in row) or row[0].strip().startswith('#'):
                    continue
                if line_num == 1 and any(h in row[0].lower() for h in ["chainguard", "customer", "image", "alternative"]):
                    continue
                alt_image = row[0].strip()
                if alt_image:
                    try:
                        alt_image = validate_image_reference(alt_image, f"alternative_image (line {line_num})")
                        images.append(alt_image)
                    except ValidationException as e:
                        logger.error(f"Validation error: {e}")
                        sys.exit(1)
        return images

    def _initialize_image_matcher(self):
        """Initialize ImageMatcher with all dependencies."""
        from utils.image_matcher import ImageMatcher
        from utils.registry_access import RegistryAccessChecker
        from utils.upstream_finder import UpstreamImageFinder

        # Initialize registry access checker to skip upstream discovery for public registries
        registry_checker = RegistryAccessChecker()

        upstream_finder = None
        if not self.args.skip_public_repo_search:
            logger.info("Upstream discovery enabled")
            upstream_finder = UpstreamImageFinder(
                manual_mappings_file=self.args.upstream_mappings_file,
                min_confidence=self.args.upstream_confidence,
            )
        llm_matcher = None
        if not self.args.disable_llm_matching:
            from utils.llm_matcher import LLMMatcher
            logger.info(f"LLM matching enabled (model: {self.args.llm_model}, threshold: {self.args.llm_confidence_threshold:.0%})")
            llm_matcher = LLMMatcher(
                api_key=self.args.anthropic_api_key,
                model=self.args.llm_model,
                cache_dir=self.args.cache_dir,
                confidence_threshold=self.args.llm_confidence_threshold,
            )
        # Check if FIPS mode is enabled
        prefer_fips = getattr(self.args, 'with_fips', False)
        if prefer_fips:
            logger.info("FIPS mode enabled - will prefer -fips variants when available")

        return ImageMatcher(
            cache_dir=self.args.cache_dir,
            dfc_mappings_file=self.args.dfc_mappings_file,
            upstream_finder=upstream_finder,
            llm_matcher=llm_matcher,
            registry_checker=registry_checker,
            prefer_fips=prefer_fips,
        )

    def _auto_match_images(self, images: list[str], matcher) -> tuple[list[ImagePair], list[str]]:
        """Auto-match alternative images to Chainguard equivalents."""
        from utils.dfc_contributor import DFCContributor
        from utils.image_matcher import MatchResult
        from utils.manual_mapping_populator import ManualMappingPopulator
        dfc_contributor = DFCContributor(output_dir=Path("output")) if self.args.generate_dfc_pr else None
        if dfc_contributor:
            logger.info("DFC contribution generation enabled")
        mapping_populator = ManualMappingPopulator() if not self.args.disable_mapping_auto_population else None
        if mapping_populator:
            logger.debug("Auto-population of manual mappings enabled (use --disable-mapping-auto-population to turn off)")
        pairs, unmatched = [], []
        matched_pairs: list[tuple[str, MatchResult]] = []  # For summary CSV
        for alt_image in images:
            result = matcher.match(alt_image)
            if result.chainguard_image and result.confidence >= self.args.min_confidence:
                upstream_info = f" (via upstream: {result.upstream_image})" if result.upstream_image else ""
                logger.info(f"✓ Matched: {alt_image} → {result.chainguard_image} (confidence: {result.confidence:.0%}, method: {result.method}){upstream_info}")
                pairs.append(ImagePair(result.chainguard_image, alt_image, upstream_image=result.upstream_image))
                matched_pairs.append((alt_image, result))
                if dfc_contributor and result.method in ["heuristic", "llm"]:
                    dfc_contributor.add_match(alt_image, result)
                if mapping_populator and result.method in ["heuristic", "llm"]:
                    mapping_populator.add_match(alt_image, result)
            else:
                logger.warning(f"✗ No match found for: {alt_image}")
                unmatched.append(alt_image)
        if mapping_populator and mapping_populator.new_mappings:
            count = mapping_populator.populate_mappings()
            if count > 0:
                logger.info(f"\nAuto-populated {count} manual mappings for future Tier 2 lookups.")
        if dfc_contributor and dfc_contributor.suggestions:
            dfc_files = dfc_contributor.generate_all()
            if dfc_files:
                logger.info("\nDFC contribution files generated:")
                for file_type, file_path in dfc_files.items():
                    logger.info(f"  - {file_type}: {file_path}")

        # Search GitHub issues for unmatched images and generate summary CSV
        issue_matches: list[tuple[str, IssueMatchResult]] = []
        no_issue_matches: list[str] = []
        if unmatched:
            unmatched_list = "\n".join(f"  - {img}" for img in unmatched)
            logger.warning(f"\n{len(unmatched)} images could not be auto-matched:\n{unmatched_list}\n")
            issue_matches, no_issue_matches = self._search_github_issues_for_unmatched(unmatched)

        # Display successful matches summary
        if pairs:
            matches_list = "\n".join(
                f"  {pair.alternative_image} ⇒ {pair.chainguard_image}"
                for pair in pairs
            )
            logger.info(f"\nSuccessful matches:\n{matches_list}")

        # Generate summary CSV
        self._generate_summary_csv(images, matched_pairs, issue_matches, no_issue_matches)

        return pairs, unmatched

    def _search_github_issues_for_unmatched(
        self, unmatched: list[str]
    ) -> tuple[list[tuple[str, IssueMatchResult]], list[str]]:
        """Search GitHub issues for unmatched images.

        Returns:
            Tuple of (issue_matches, no_issue_matches). Returns empty lists on error.
        """
        try:
            issue_matches, no_issue_matches = search_github_issues_for_images(
                unmatched_images=unmatched,
                anthropic_api_key=self.args.anthropic_api_key,
                llm_model=self.args.llm_model,
                cache_dir=self.args.cache_dir,
                confidence_threshold=self.args.llm_confidence_threshold,
                github_token=getattr(self.args, 'github_token', None),
            )
            log_issue_search_results(issue_matches, no_issue_matches)
            return issue_matches, no_issue_matches
        except ValueError as e:
            # GitHub token not available - skip issue search silently
            logger.debug(f"GitHub issue search skipped: {e}")
            return [], unmatched
        except Exception as e:
            logger.warning(f"GitHub issue search failed: {e}")
            return [], unmatched

    def _generate_summary_csv(
        self,
        all_images: list[str],
        matched_pairs: list[tuple[str, MatchResult]],
        issue_matches: list[tuple[str, IssueMatchResult]],
        no_issue_matches: list[str],
    ) -> None:
        """Generate summary CSV for all input images."""
        # Ensure output directory exists
        self.args.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate the summary CSV filename
        safe_customer_name = sanitize_customer_name(self.args.customer_name)
        summary_csv_path = self.args.output_dir / f"{safe_customer_name}_gauge_summary.csv"

        # Check if FIPS mode is enabled
        prefer_fips = getattr(self.args, 'with_fips', False)

        # Write the summary CSV
        write_summary_csv(
            file_path=summary_csv_path,
            all_images=all_images,
            matched_pairs=matched_pairs,
            issue_matches=issue_matches,
            no_issue_matches=no_issue_matches,
            prefer_fips=prefer_fips,
        )
        logger.info(f"Summary CSV written to: {summary_csv_path}")

    def _execute_scans(self) -> list:
        """Execute scans with checkpoint/resume support."""
        from core.persistence import ScanResultPersistence
        persistence = ScanResultPersistence(self.args.checkpoint_file)

        # Handle retry-failures mode
        if getattr(self.args, 'retry_failures', False):
            logger.info(f"Retry mode: loading failures from checkpoint: {self.args.checkpoint_file}")
            results, metadata = persistence.load_results()

            skip_permanent = getattr(self.args, 'skip_permanent_failures', False)
            failed_pairs = persistence.get_failed_pairs(skip_permanent)

            if not failed_pairs:
                logger.info("No failed scans to retry.")
                return results

            logger.info(f"Retrying {len(failed_pairs)} failed comparisons...")
            try:
                retry_results = self.scanner.scan_image_pairs_parallel(failed_pairs)
            except KeyboardInterrupt:
                logger.warning("\nRetry interrupted! Partial results saved to checkpoint.")
                sys.exit(1)

            # Merge and save
            merged = persistence.merge_retry_results(retry_results)
            persistence.save_results(merged, metadata=metadata)

            # Log summary
            succeeded = sum(1 for r in retry_results if r.scan_successful)
            failed = len(retry_results) - succeeded
            logger.info(f"Retry complete: {succeeded} succeeded, {failed} failed")

            return merged

        if self.args.resume and persistence.exists():
            logger.info(f"Resuming from checkpoint: {self.args.checkpoint_file}")
            results, _ = persistence.load_results()
            logger.info(f"Loaded {len(results)} previous scan results")
            scanned_pairs = {(r.pair.alternative_image, r.pair.chainguard_image) for r in results if r.scan_successful}
            remaining_pairs = [p for p in self.pairs if (p.alternative_image, p.chainguard_image) not in scanned_pairs]
            if remaining_pairs:
                logger.info(f"Scanning {len(remaining_pairs)} remaining pairs...")
                new_results = self.scanner.scan_image_pairs_parallel(remaining_pairs)
                results.extend(new_results)
                persistence.save_results(results)
            else:
                logger.info("All pairs already scanned, using checkpoint results")
        else:
            logger.info("Starting vulnerability scans...")
            try:
                results = self.scanner.scan_image_pairs_parallel(self.pairs)
                persistence.save_results(results, metadata={"pairs_count": len(self.pairs), "platform": self.args.platform})
                logger.debug(f"Checkpoint saved: {self.args.checkpoint_file}")
            except KeyboardInterrupt:
                logger.warning("\nScan interrupted! Partial results saved to checkpoint.")
                logger.info(f"Run with --resume to continue from: {self.args.checkpoint_file}")
                sys.exit(1)
        return results

    def _generate_reports(self, safe_customer_name: str, output_types: set) -> dict:
        """Generate output reports based on requested types."""
        self.args.output_dir.mkdir(parents=True, exist_ok=True)
        output_files = {}
        if "vuln_summary" in output_types:
            html_path = self.args.output_dir / f"{safe_customer_name}_assessment.html"
            generator = HTMLGenerator()
            exec_summary = self.args.exec_summary if self.args.exec_summary.exists() else None
            appendix = self.args.appendix if self.args.appendix.exists() else None
            html_config = HTMLGeneratorConfig(
                customer_name=self.args.customer_name,
                platform=self.args.platform,
                exec_summary_path=exec_summary,
                appendix_path=appendix,
                kev_catalog=self.kev_catalog,
                include_negligible=self.args.include_negligible,
            )
            generator.generate(self.results, html_path, html_config)
            output_files["vuln_summary"] = html_path
        if "cost_analysis" in output_types:
            xlsx_path = self.args.output_dir / f"{safe_customer_name}_cost_analysis.xlsx"
            generator = XLSXGenerator()
            xlsx_config = XLSXGeneratorConfig(
                customer_name=self.args.customer_name,
                platform=self.args.platform,
                hours_per_vuln=self.args.hours_per_vuln,
                hourly_rate=self.args.hourly_rate,
                auto_detect_fips=self.args.with_fips,
                kev_catalog=self.kev_catalog,
                include_negligible=self.args.include_negligible,
            )
            generator.generate(self.results, xlsx_path, xlsx_config)
            output_files["cost_analysis"] = xlsx_path
        if "pricing" in output_types:
            pricing_files = self._generate_pricing_quote(safe_customer_name)
            output_files.update(pricing_files)
        return output_files

    def _generate_pricing_quote(self, safe_customer_name: str) -> dict:
        """Generate pricing quote reports (HTML and TXT)."""
        from utils.image_classifier import ImageClassifier
        from utils.pricing_calculator import PricingCalculator
        from outputs.pricing_quote_generator import PricingQuoteGenerator
        output_files = {}
        try:
            if not self.args.pricing_policy.exists():
                raise FileNotFoundError(f"Pricing policy file not found: {self.args.pricing_policy}. "
                                      f"Use --pricing-policy to specify one.")
            calculator = PricingCalculator.from_policy_file(self.args.pricing_policy)
            logger.info(f"Loaded pricing policy: {calculator.policy.policy_name}")
            logger.info("Classifying Chainguard images by tier...")
            classifier = ImageClassifier(github_token=None, auto_update=True)
            chainguard_images = [r.pair.chainguard_image for r in self.results if r.scan_successful]
            tier_images = defaultdict(list)
            tier_counts = Counter()
            for image in chainguard_images:
                try:
                    tier = classifier.get_image_tier(image)
                    tier_counts[tier] += 1
                    tier_images[tier].append(image)
                except ValueError as e:
                    logger.warning(f"Could not classify image {image}: {e}")
            if not tier_counts:
                logger.warning("No images classified for pricing. Skipping quote generation.")
            else:
                quote_data = calculator.calculate_quote(dict(tier_counts), dict(tier_images))
                generator = PricingQuoteGenerator(customer_name=self.args.customer_name)
                html_path = self.args.output_dir / f"{safe_customer_name}_pricing_quote.html"
                generator.generate_html_quote(quote_data, html_path)
                output_files["pricing_html"] = html_path
                text_path = self.args.output_dir / f"{safe_customer_name}_pricing_quote.txt"
                generator.generate_text_quote(quote_data, text_path)
                output_files["pricing_txt"] = text_path
        except Exception as e:
            logger.error(f"Pricing quote generation failed: {e}", exc_info=True)
        return output_files
