import java.security.KeyPairGenerator;
import java.security.MessageDigest;
import java.security.Signature;

public class Signer {
    public static byte[] sign(byte[] data) throws Exception {
        KeyPairGenerator kpg = KeyPairGenerator.getInstance("EC");
        Signature sig = Signature.getInstance("SHA256withECDSA");
        MessageDigest md = MessageDigest.getInstance("SHA-1");
        return md.digest(data);
    }
}
