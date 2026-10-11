using System.Security.Cryptography;
using System.Text;
using CleanerPro.Detection.Rules;

// Maintainer tool for the detection rule database.
//   keygen <private-key.pem>               create an ECDSA P-256 key pair (prints the public key)
//   validate <rules.json>                  validate a rule database for every platform
//   sign <rules.json> <private-key.pem>    write rules.json.sig next to the database
//   verify <rules.json> <public-key>       verify rules.json.sig with a base64 public key
// Private keys must never be committed (the repository .gitignore excludes *.private.pem).

if (args.Length == 0)
{
    return Usage();
}

try
{
    switch (args[0])
    {
        case "keygen" when args.Length == 2:
        {
            if (File.Exists(args[1]))
            {
                Console.Error.WriteLine($"{args[1]} already exists; refusing to overwrite a key.");
                return 2;
            }

            var (privatePem, publicKey) = RuleSignature.GenerateKeyPair();
            File.WriteAllText(args[1], privatePem);
            Console.WriteLine("Private key written to " + args[1] + " (keep it secret and out of source control).");
            Console.WriteLine("Public key (add to ruleUpdates.additionalTrustedPublicKeys or RuleSignature.BuiltInTrustedPublicKeys):");
            Console.WriteLine(publicKey);
            Console.WriteLine("Fingerprint: " + RuleSignature.Fingerprint(publicKey));
            return 0;
        }

        case "validate" when args.Length == 2:
        {
            var bytes = File.ReadAllBytes(args[1]);
            var ok = true;
            foreach (var platform in new[] { "windows", "linux", "macos" })
            {
                var outcome = RuleDatabaseLoader.Load(bytes, platform);
                if (!outcome.Succeeded)
                {
                    ok = false;
                    Console.Error.WriteLine($"[{platform}] invalid:");
                    foreach (var error in outcome.Errors)
                    {
                        Console.Error.WriteLine("  - " + error);
                    }
                }
                else
                {
                    Console.WriteLine($"[{platform}] valid: {outcome.Database!.DisplayVersion}, {outcome.Database.Rules.Count} rules, SHA-256 {outcome.Database.Sha256}");
                }
            }

            return ok ? 0 : 1;
        }

        case "sign" when args.Length == 3:
        {
            var bytes = File.ReadAllBytes(args[1]);
            var outcome = RuleDatabaseLoader.Load(bytes, "windows");
            if (!outcome.Succeeded)
            {
                Console.Error.WriteLine("Refusing to sign an invalid database: " + string.Join(" ", outcome.Errors));
                return 1;
            }

            if (outcome.Database!.Document.ExpiresAt is null)
            {
                Console.Error.WriteLine("Warning: expiresAt is null. The application rejects downloaded updates without an expiry date.");
            }

            using var key = ECDsa.Create();
            key.ImportFromPem(File.ReadAllText(args[2]));
            var signature = RuleSignature.Sign(bytes, key);
            File.WriteAllText(args[1] + ".sig", signature, new UTF8Encoding(false));
            Console.WriteLine("Signature written to " + args[1] + ".sig");
            return 0;
        }

        case "verify" when args.Length == 3:
        {
            var bytes = File.ReadAllBytes(args[1]);
            var signature = File.ReadAllText(args[1] + ".sig");
            var valid = RuleSignature.Verify(bytes, signature, [args[2]], out var fingerprint);
            Console.WriteLine(valid ? $"Signature valid (key {fingerprint})." : "Signature INVALID.");
            return valid ? 0 : 1;
        }

        default:
            return Usage();
    }
}
catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or CryptographicException or ArgumentException)
{
    Console.Error.WriteLine("Error: " + ex.Message);
    return 2;
}

static int Usage()
{
    Console.Error.WriteLine("Usage: CleanerPro.RuleTool keygen <private.pem> | validate <rules.json> | sign <rules.json> <private.pem> | verify <rules.json> <public-key-base64>");
    return 64;
}
