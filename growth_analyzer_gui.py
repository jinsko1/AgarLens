from opencv_growth_ui import OpenCVGrowthUI, parse_args


if __name__ == "__main__":
    args = parse_args()
    app = OpenCVGrowthUI(args.paths)
    app.run()
