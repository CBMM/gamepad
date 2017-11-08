import argparse


if __name__ == "__main__":
    # Set up command line
    argparser = argparse.ArgumentParser()
    argparser.add_argument("log", help="Enter the log you want to chunk")
    argparser.add_argument("out", help="Location of output")
    args = argparser.parse_args()

    with open(args.log, 'r') as f:
        out = None
        while True:
            line = f.readline()
            if line == "":
                print("EOF")
                break
            elif line.startswith("COQC"):
                # close open file if open
                if out:
                    out.close()

                # open file for writing
                toks = line.split(" ")
                v_file = toks[1].strip()
                print("COQC", v_file)
                out = open("{}/{}.dump".format(args.out, v_file), 'w')
            elif out:
                # write if file open for writing
                out.write(line)
            else:
                pass
                # print("Skipping")
                # out.write(line)
